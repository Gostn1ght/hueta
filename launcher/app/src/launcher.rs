//! Режим лаунчера: проверка, обновление, запуск игры.

use crate::brand::{Brand, Renderer};
use crate::sys::{self, LogFile};
use gamesync::local::Local;
use gamesync::util::human_bytes;
use gamesync::{Engine, Options, Progress, QuickCheck, Reporter, Sources};
type GameRelease = gamesync::Release;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering::*};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Метка в exe: `packer launcher` и панель сервера берут из неё номер версии при публикации.
#[used]
#[no_mangle]
pub static LZ_LAUNCHER_VERSION_MARK: &str = concat!("LZLAUNCHER_VERSION=", env!("CARGO_PKG_VERSION"), ";");

#[derive(Serialize, Deserialize, Default, Clone)]
pub struct Settings {
    pub renderer: usize,
    #[serde(default)]
    pub seed: Option<bool>,
    pub ip: String,
    pub port: String,
    pub login: String,
    pub password: String,
}

pub struct St {
    pub brand: Brand,
    pub dir: PathBuf,
    pub settings: Mutex<Settings>,
    pub release: Mutex<Option<GameRelease>>,
    pub offline: Mutex<Option<String>>,
    pub quick: Mutex<Option<QuickCheck>>,
    pub busy: AtomicBool,
    pub cancel: Arc<AtomicBool>,
    pub sources: Arc<Sources>,
    pub log: Arc<LogFile>,
    pub seeding: Mutex<Option<(String, String)>>,
    pub announcer: AtomicBool,
    /// `--master`: папка — мастер-копия владельца (из неё собирается раздача).
    /// Лаунчер только запускает игру: никаких обновлений, проверок и раздачи.
    pub master: bool,
    /// Куда лаунчер пишет свои настройки, журнал и ключ P2P: папка игры,
    /// а в режиме `--master` — папка самого лаунчера (мастер-копия остаётся чистой).
    pub state: PathBuf,
}

impl St {
    pub fn new(brand: Brand, dir: PathBuf, master: bool) -> Self {
        let sources = Arc::new(Sources::new(&brand.base_urls, Duration::from_secs(10)).expect("base_urls"));
        let state = if master {
            std::env::current_exe().ok().and_then(|e| e.parent().map(PathBuf::from)).unwrap_or_else(|| dir.clone())
        } else {
            dir.clone()
        };
        let settings = std::fs::read(state.join(".launcher/settings.json"))
            .ok()
            .and_then(|b| serde_json::from_slice::<Settings>(&b).ok())
            .map(|mut s| {
                s.password = sys::unprotect(&s.password);
                s
            })
            .unwrap_or_default();
        Self {
            log: Arc::new(LogFile::new(&state)),
            brand,
            dir,
            settings: Mutex::new(settings),
            release: Mutex::new(None),
            offline: Mutex::new(None),
            quick: Mutex::new(None),
            busy: AtomicBool::new(false),
            cancel: Arc::new(AtomicBool::new(false)),
            sources,
            seeding: Mutex::new(None),
            announcer: AtomicBool::new(false),
            master,
            state,
        }
    }

    fn seed_enabled(&self) -> bool {
        !self.master && self.settings.lock().seed.unwrap_or(self.brand.p2p_seed_default)
    }

    fn save_settings(&self) -> anyhow::Result<()> {
        let mut s = self.settings.lock().clone();
        s.password = sys::protect(&s.password);
        std::fs::create_dir_all(self.state.join(".launcher"))?;
        std::fs::write(self.state.join(".launcher/settings.json"), serde_json::to_vec_pretty(&s)?)?;
        Ok(())
    }
}

type S<'a> = tauri::State<'a, Arc<St>>;

#[derive(Serialize, Clone)]
struct SplashMsg {
    text: String,
    pct: f64,
}

fn splash(app: &AppHandle, text: &str, pct: f64) {
    let _ = app.emit("splash", SplashMsg { text: text.into(), pct });
}

#[tauri::command]
pub async fn boot(app: AppHandle, st: S<'_>) -> Result<(), String> {
    let st = st.inner().clone();
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let _ = std::fs::remove_file(exe.with_extension("exe.old"));
    st.log.line(&format!("Лаунчер {VERSION}, папка {}", st.dir.display()));

    splash(&app, "Проверка файлов игры…", 0.15);
    let dir = st.dir.clone();
    let uf = st.brand.user_files.clone();
    let q = tokio::task::spawn_blocking(move || gamesync::quick_check(&dir, &uf)).await.ok().flatten();
    match &q {
        Some(q) if q.ok == q.total => splash(&app, &format!("Найдены все файлы игры ({})", q.total), 0.45),
        Some(q) => splash(&app, &format!("Требуют проверки: {} файлов", q.total - q.ok), 0.45),
        None => splash(&app, "Игра ещё не установлена", 0.45),
    }
    *st.quick.lock() = q;

    if st.sources.has_p2p() && st.sources.node().is_none() {
        splash(&app, "Запуск P2P…", 0.5);
        match gamesync::p2p::P2pNode::bind(Some(&st.state.join(".launcher").join("p2p.key")), 4, st.brand.p2p_hide_ip, &st.brand.p2p_relays).await {
            Ok(n) => {
                st.log.line(&format!("P2P-узел: {}", n.id()));
                st.sources.set_node(n);
            }
            Err(e) => st.log.line(&format!("P2P не запустился: {e:#}")),
        }
    }

    splash(&app, "Связь с сервером…", 0.6);
    match tokio::time::timeout(Duration::from_secs(12), gamesync::fetch_release(&st.sources, &st.brand.public_key)).await {
        Ok(Ok(r)) => {
            *st.release.lock() = Some(r);
            *st.offline.lock() = None;
        }
        Ok(Err(e)) => {
            st.log.line(&format!("Сервер недоступен: {e:#}"));
            *st.offline.lock() = Some(format!("{e:#}"));
        }
        Err(_) => *st.offline.lock() = Some("сервер не ответил за 12 с".into()),
    }

    let lr = st.release.lock().as_ref().and_then(|r| r.launcher.clone());
    // The verified signed release is used for portable and installed launchers.
    // Master copies retain their explicit no-update policy. Compare bytes rather
    // than version labels so a mislabeled publication cannot cause a restart loop.
    let own_hash = if !st.master && lr.is_some() {
        let e = exe.clone();
        tokio::task::spawn_blocking(move || std::fs::read(&e).map(|b| hex::encode(blake3::hash(&b).as_bytes())).ok()).await.ok().flatten()
    } else {
        None
    };
    if let (Some(l), Some(own)) = (lr, own_hash) {
        if l.hash != own && !cfg!(debug_assertions) {
            splash(&app, &format!("Обновление лаунчера до {}…", l.version), 0.75);
            match self_update(&app, &st, &l).await {
                Ok(()) => {
                    st.log.line(&format!("Лаунчер обновлён до {}", l.version));
                    app.exit(0);
                    return Ok(());
                }
                Err(e) => st.log.line(&format!("Не удалось обновить лаунчер: {e:#}")),
            }
        }
    }
    refresh_seed(&st).await;
    splash(&app, "Готово", 1.0);
    Ok(())
}

/// Включить/выключить раздачу игры другим игрокам по настройке и состоянию установки.
pub async fn refresh_seed(st: &Arc<St>) {
    let Some(node) = st.sources.node().cloned() else { return };
    if !st.seed_enabled() || st.busy.load(Relaxed) {
        node.set_provider(None);
        *st.seeding.lock() = None;
        return;
    }
    let dir = st.dir.clone();
    let idx = tokio::task::spawn_blocking(move || gamesync::p2p::SeedIndex::build(&dir)).await.ok().flatten();
    let server_hash = st.release.lock().as_ref().map(|r| r.manifest_hash.clone());
    match idx {
        // Раздаём только актуальную версию — старая никому не нужна.
        Some(i) if i.chunks() > 0 && server_hash.as_deref().map_or(true, |h| h == i.manifest_hash) => {
            *st.seeding.lock() = Some((i.manifest_hash.clone(), i.version.clone()));
            node.set_provider(Some(Arc::new(i)));
        }
        _ => {
            node.set_provider(None);
            *st.seeding.lock() = None;
        }
    }
    if !st.announcer.swap(true, AcqRel) {
        let st = st.clone();
        tauri::async_runtime::spawn(async move {
            loop {
                let cur = st.seeding.lock().clone();
                if let (Some((mh, ver)), Some(node)) = (cur, st.sources.node().cloned()) {
                    for s in st.sources.p2p_servers() {
                        let _ = tokio::time::timeout(Duration::from_secs(30), node.announce(s, &mh, &ver)).await;
                    }
                }
                tokio::time::sleep(Duration::from_secs(60)).await;
            }
        });
    }
}

async fn self_update(app: &AppHandle, st: &St, l: &gamesync::manifest::LauncherRelease) -> anyhow::Result<()> {
    let b = st
        .sources
        .download_chunked(&l.path, l.size, &|done, total| {
            splash(app, &format!("Обновление лаунчера до {}: {} из {}", l.version, human_bytes(done), human_bytes(total)), 0.75 + 0.2 * done as f64 / total.max(1) as f64)
        })
        .await?;
    if hex::encode(blake3::hash(&b).as_bytes()) != l.hash {
        anyhow::bail!("хеш нового лаунчера не совпал");
    }
    let exe = std::env::current_exe()?;
    let new = exe.with_extension("exe.new");
    let old = exe.with_extension("exe.old");
    std::fs::write(&new, &b)?;
    let _ = std::fs::remove_file(&old);
    std::fs::rename(&exe, &old)?;
    if let Err(e) = std::fs::rename(&new, &exe) {
        let _ = std::fs::rename(&old, &exe);
        return Err(e.into());
    }
    // Preserve the explicit game directory after updating a portable launcher
    // that lives elsewhere. A failed restart rolls the executable back as well.
    let args = restart_arguments(std::env::args_os().skip(1), &st.dir);
    if let Err(e) = std::process::Command::new(&exe).args(args).current_dir(&st.dir).spawn() {
        let _ = std::fs::remove_file(&exe);
        std::fs::rename(&old, &exe)?;
        return Err(e.into());
    }
    Ok(())
}

fn restart_arguments(args: impl IntoIterator<Item = std::ffi::OsString>, dir: &std::path::Path) -> Vec<std::ffi::OsString> {
    let mut args: Vec<_> = args.into_iter().collect();
    if !args.iter().any(|a| a == "--dir") {
        args.push("--dir".into());
        args.push(dir.as_os_str().to_owned());
    }
    if !args.iter().any(|a| a == "--launcher") { args.push("--launcher".into()); }
    args
}

#[cfg(test)]
mod restart_tests {
    use super::restart_arguments;
    use std::{ffi::OsString, path::Path};
    #[test]
    fn portable_restart_keeps_unicode_directory_and_flags() {
        let args = restart_arguments([OsString::from("--quiet")], Path::new("J:/Игры/Lost Zone"));
        assert_eq!(args, ["--quiet", "--dir", "J:/Игры/Lost Zone", "--launcher"].map(OsString::from));
        let explicit = ["--dir", "J:/Other game", "--launcher"].map(OsString::from);
        assert_eq!(restart_arguments(explicit.clone(), Path::new("J:/Ignored")), explicit);
    }
}

#[tauri::command]
pub fn show_main(app: AppHandle) {
    // Главное окно грузится скрытым ещё во время заставки — сообщаем, что проверка закончилась.
    let _ = app.emit("booted", ());
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
    if let Some(w) = app.get_webview_window("splash") {
        let _ = w.close();
    }
}

#[derive(Serialize)]
pub struct Info {
    product: String,
    title: String,
    launcher_version: String,
    installed: Option<String>,
    server: Option<String>,
    game_size: Option<u64>,
    status: String,
    status_text: String,
    offline: Option<String>,
    renderers: Vec<Renderer>,
    settings: Settings,
    busy: bool,
    can_play: bool,
    auto_update: bool,
    p2p: bool,
    seed: bool,
    seeding: bool,
    seed_sent: u64,
}

#[tauri::command]
pub fn info(st: S<'_>) -> Info {
    build_info(&st)
}

fn build_info(st: &St) -> Info {
    let installed = Local::new(&st.dir).installed();
    let rel = st.release.lock().clone();
    let quick = st.quick.lock().clone();
    let busy = st.busy.load(Relaxed);
    let broken = quick.as_ref().map(|q| q.ok != q.total).unwrap_or(false);
    let (status, text) = if busy {
        ("busy", "Идёт обновление…".to_string())
    } else if st.master {
        ("master", "Мастер-копия: только запуск, файлы не обновляются".to_string())
    } else if installed.is_none() {
        ("not_installed", if rel.is_some() { "Игра не установлена".into() } else { "Игра не установлена, сервер недоступен".into() })
    } else if let Some(r) = &rel {
        if installed.as_ref().map(|i| i.manifest_hash != r.manifest_hash).unwrap_or(true) {
            ("update", format!("Доступно обновление {}", r.version))
        } else if broken {
            ("broken", "Часть файлов изменена — нужна проверка".into())
        } else {
            ("latest", "Установлена последняя версия".into())
        }
    } else {
        ("offline", "Нет связи с сервером".into())
    };
    // Значения с блокировками — отдельными операторами: временный guard в литерале
    // структуры живёт до конца выражения, повторная блокировка того же мьютекса = зависание.
    let settings = st.settings.lock().clone();
    let seed = st.seed_enabled();
    let seeding = st.seeding.lock().is_some();
    let offline = st.offline.lock().clone();
    Info {
        product: st.brand.product.clone(),
        title: st.brand.title.clone(),
        launcher_version: VERSION.into(),
        installed: installed.map(|i| i.version),
        server: rel.as_ref().map(|r| r.version.clone()),
        game_size: rel.as_ref().map(|r| r.game_size),
        status: status.into(),
        status_text: text,
        offline,
        renderers: st.brand.renderers.clone(),
        settings,
        busy,
        can_play: !busy && matches!(status, "latest" | "offline" | "broken" | "update" | "master"),
        auto_update: st.brand.auto_update,
        p2p: st.sources.node().is_some(),
        seed,
        seeding,
        seed_sent: st.sources.node().map(|n| n.stats.sent.load(Relaxed)).unwrap_or(0),
    }
}

#[tauri::command]
pub async fn check_update(st: S<'_>) -> Result<Info, String> {
    let st = st.inner().clone();
    match gamesync::fetch_release(&st.sources, &st.brand.public_key).await {
        Ok(r) => {
            *st.release.lock() = Some(r);
            *st.offline.lock() = None;
        }
        Err(e) => {
            *st.offline.lock() = Some(format!("{e:#}"));
            return Err(format!("Сервер недоступен: {e:#}"));
        }
    }
    let dir = st.dir.clone();
    let uf = st.brand.user_files.clone();
    *st.quick.lock() = tokio::task::spawn_blocking(move || gamesync::quick_check(&dir, &uf)).await.ok().flatten();
    Ok(build_info(&st))
}

struct UiRep {
    app: AppHandle,
    log: Arc<LogFile>,
    buf: Mutex<(Vec<String>, Instant)>,
}

impl UiRep {
    fn flush(&self) {
        let lines = {
            let mut b = self.buf.lock();
            b.1 = Instant::now();
            std::mem::take(&mut b.0)
        };
        if !lines.is_empty() {
            let _ = self.app.emit("log", lines);
        }
    }
}

impl Reporter for UiRep {
    fn progress(&self, p: &Progress) {
        let _ = self.app.emit("progress", p);
        self.flush();
    }
    fn log(&self, line: &str) {
        self.log.line(line);
        let due = {
            let mut b = self.buf.lock();
            // В журнале окна держим разумный поток: мелкие «✓ файл» прореживаем.
            if b.0.len() < 400 {
                b.0.push(line.to_string());
            }
            b.1.elapsed() > Duration::from_millis(200)
        };
        if due {
            self.flush();
        }
    }
}

#[derive(Serialize, Clone)]
struct Done {
    ok: bool,
    cancelled: bool,
    message: String,
}

#[tauri::command]
pub fn start_sync(app: AppHandle, st: S<'_>, verify: bool) -> Result<(), String> {
    if st.master {
        return Err("Это мастер-копия игры: лаунчер её не обновляет".into());
    }
    let st = st.inner().clone();
    if st.busy.swap(true, AcqRel) {
        return Err("Уже выполняется".into());
    }
    st.cancel.store(false, Release);
    if let Some(n) = st.sources.node() {
        // Во время обновления файлы меняются — раздачу ставим на паузу.
        n.set_provider(None);
        *st.seeding.lock() = None;
    }
    tauri::async_runtime::spawn(async move {
        let rep = Arc::new(UiRep { app: app.clone(), log: st.log.clone(), buf: Mutex::new((vec![], Instant::now())) });
        let res: anyhow::Result<gamesync::Summary> = async {
            let rel = match gamesync::fetch_release(&st.sources, &st.brand.public_key).await {
                Ok(r) => {
                    *st.release.lock() = Some(r.clone());
                    *st.offline.lock() = None;
                    r
                }
                Err(e) => {
                    *st.offline.lock() = Some(format!("{e:#}"));
                    return Err(e);
                }
            };
            rep.log(&format!("Сервер: версия {} ({})", rel.version, human_bytes(rel.game_size)));
            let (m, b) = gamesync::fetch_manifest(&st.sources, &rel).await?;
            let eng = Engine {
                dir: st.dir.clone(),
                sources: st.sources.clone(),
                opts: Options {
                    connections: st.brand.connections,
                    max_retries: st.brand.max_retries,
                    keep: st.brand.keep.clone(),
                    clean_on_update: st.brand.clean_on_update.clone(),
                    user_files: st.brand.user_files.clone(),
                    ..Default::default()
                },
                cancel: st.cancel.clone(),
                rep: rep.clone(),
            };
            eng.sync(m, &b, &rel, verify).await
        }
        .await;
        let done = match res {
            Ok(s) => {
                let msg = format!(
                    "Готово за {:.0} с. Версия {}. Скачано {}{}, собрано локально {}, обновлено файлов {}{}",
                    s.seconds,
                    s.version,
                    human_bytes(s.network),
                    if s.from_peers > 0 { format!(" (от игроков {})", human_bytes(s.from_peers)) } else { String::new() },
                    human_bytes(s.copied),
                    s.written_files,
                    if s.deleted > 0 { format!(", удалено {}", s.deleted) } else { String::new() }
                );
                rep.log(&msg);
                Done { ok: true, cancelled: false, message: msg }
            }
            Err(e) if gamesync::is_cancelled(&e) => {
                rep.log("Остановлено. Продолжится с того же места.");
                Done { ok: false, cancelled: true, message: "Остановлено".into() }
            }
            Err(e) => {
                let msg = format!("Ошибка: {e:#}");
                rep.log(&msg);
                Done { ok: false, cancelled: false, message: msg }
            }
        };
        rep.flush();
        let dir = st.dir.clone();
        let uf = st.brand.user_files.clone();
        *st.quick.lock() = tokio::task::spawn_blocking(move || gamesync::quick_check(&dir, &uf)).await.ok().flatten();
        st.busy.store(false, Release);
        refresh_seed(&st).await;
        let _ = app.emit("sync-done", done);
    });
    Ok(())
}

#[tauri::command]
pub fn cancel_sync(st: S<'_>) {
    st.cancel.store(true, Release);
}

#[tauri::command]
pub fn save_settings(st: S<'_>, ip: String, port: String, login: String, password: String) -> Result<(), String> {
    {
        let mut s = st.settings.lock();
        s.ip = ip.trim().into();
        s.port = port.trim().into();
        s.login = login.trim().into();
        s.password = password;
    }
    st.save_settings().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_renderer(st: S<'_>, index: usize) -> Result<(), String> {
    if index >= st.brand.renderers.len() {
        return Err("нет такого рендера".into());
    }
    st.settings.lock().renderer = index;
    st.save_settings().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_addons(st: S<'_>) -> Vec<crate::addons::Addon> { crate::addons::list(&st.dir) }

#[tauri::command]
pub fn set_addon(st: S<'_>, id: String, install: bool, replace_conflicts: bool) -> Result<Vec<crate::addons::Addon>, String> {
    if st.busy.compare_exchange(false, true, AcqRel, Relaxed).is_err() { return Err("Дождитесь окончания обновления".into()); }
    let result = crate::addons::change(&st.dir, &id, install, replace_conflicts);
    st.busy.store(false, Release);
    result?;
    st.log.line(&format!("Аддон {id}: {}; новое меню откроется при следующем запуске игры", if install { "установлен" } else { "удалён" }));
    Ok(crate::addons::list(&st.dir))
}

#[tauri::command]
pub async fn set_seed(st: S<'_>, on: bool) -> Result<(), String> {
    let st = st.inner().clone();
    st.settings.lock().seed = Some(on);
    st.save_settings().map_err(|e| e.to_string())?;
    st.log.line(if on { "Раздача включена" } else { "Раздача выключена" });
    refresh_seed(&st).await;
    Ok(())
}

#[tauri::command]
pub fn play(app: AppHandle, st: S<'_>) -> Result<(), String> {
    if st.busy.load(Relaxed) {
        return Err("Дождитесь окончания обновления".into());
    }
    let s = st.settings.lock().clone();
    let r = st.brand.renderers.get(s.renderer).or(st.brand.renderers.first()).ok_or("рендеры не настроены")?;
    let exe = st.dir.join(&r.exe);
    if !exe.exists() {
        return Err(format!("Не найден {} — нажмите «Проверить файлы»", r.exe));
    }
    if !st.brand.launch_block_file.is_empty() && st.dir.join(&st.brand.launch_block_file).exists() {
        return Err("Идёт обновление игры — дождитесь окончания".into());
    }
    prepare_launch(&st.brand, &st.dir).map_err(|e| format!("Не удалось подготовить запуск: {e:#}"))?;
    let mut args: Vec<String> = r.args.split_whitespace().map(String::from).collect();
    if !st.brand.connect_args.is_empty() && !s.ip.is_empty() {
        let t = st
            .brand
            .connect_args
            .replace("{ip}", &s.ip)
            .replace("{port}", &s.port)
            .replace("{login}", &s.login)
            .replace("{password}", &s.password);
        args.extend(t.split_whitespace().map(String::from));
    }
    let wd = st.dir.join(&st.brand.game_working_dir);
    std::process::Command::new(&exe)
        .args(&args)
        .current_dir(if wd.is_dir() { wd } else { st.dir.clone() })
        .spawn()
        .map_err(|e| format!("Не удалось запустить игру: {e}"))?;
    st.log.line(&format!("Запуск: {} {}", r.exe, r.args));
    if st.brand.minimize_on_start {
        if let Some(w) = app.get_webview_window("main") {
            let _ = w.minimize();
        }
    }
    Ok(())
}

/// Как «Play Lost Zone.cmd»: fsgame.ltx из шаблона с путём к папке игры и нужные папки.
fn prepare_launch(b: &Brand, dir: &std::path::Path) -> anyhow::Result<()> {
    if let Some(t) = &b.launch_template {
        let tpl = std::fs::read(dir.join(&t.from)).map_err(|e| anyhow::anyhow!("{}: {e}", t.from))?;
        let mut root = dir.to_string_lossy().trim_end_matches(['\\', '/']).replace('/', "\\");
        root.push('\\');
        let root = sys::to_ansi(&root);
        let mut out = Vec::with_capacity(tpl.len() + 256);
        let mut i = 0;
        while i < tpl.len() {
            if tpl[i..].starts_with(b"{ROOT}") {
                out.extend_from_slice(&root);
                i += 6;
            } else {
                out.push(tpl[i]);
                i += 1;
            }
        }
        std::fs::write(dir.join(&t.to), out)?;
    }
    for d in &b.launch_mkdirs {
        std::fs::create_dir_all(dir.join(d))?;
    }
    Ok(())
}

#[tauri::command]
pub fn open_link(st: S<'_>, which: String) -> Result<(), String> {
    let url = match which.as_str() {
        "bug" => st.brand.links.bug.clone(),
        "discord" => st.brand.links.discord.clone(),
        "youtube" => st.brand.links.youtube.clone(),
        other => other.to_string(),
    };
    sys::open_url(&url).map_err(|e| e.to_string())
}

#[derive(Serialize, Deserialize, Clone, Default)]
pub struct NewsItem {
    #[serde(default)]
    title: String,
    #[serde(default)]
    date: String,
    #[serde(default)]
    text: String,
    #[serde(default)]
    image: String,
    #[serde(default)]
    link: String,
}

#[tauri::command]
pub async fn news(st: S<'_>) -> Result<Vec<NewsItem>, String> {
    let st = st.inner().clone();
    let b = st.sources.get(&st.brand.news_url, 2 << 20).await.map_err(|e| e.to_string())?;
    let mut items: Vec<NewsItem> = serde_json::from_slice(&b).map_err(|e| e.to_string())?;
    items.truncate(20);
    for it in items.iter_mut() {
        if it.image.is_empty() || it.image.starts_with("http") {
            continue;
        }
        let rel = it.image.trim_start_matches('/').to_string();
        it.image = match tokio::time::timeout(Duration::from_secs(15), st.sources.get(&rel, 3 << 20)).await {
            Ok(Ok(b)) => {
                use base64::Engine;
                let mime = match rel.rsplit('.').next().unwrap_or("") {
                    "png" => "image/png",
                    "webp" => "image/webp",
                    "gif" => "image/gif",
                    _ => "image/jpeg",
                };
                format!("data:{mime};base64,{}", base64::engine::general_purpose::STANDARD.encode(b))
            }
            _ => String::new(),
        };
    }
    Ok(items)
}

#[tauri::command]
pub async fn quit(app: AppHandle, st: S<'_>) -> Result<(), String> {
    let st = st.inner().clone();
    if st.busy.load(Relaxed) {
        st.cancel.store(true, Release);
        for _ in 0..100 {
            if !st.busy.load(Relaxed) {
                break;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }
    app.exit(0);
    Ok(())
}
