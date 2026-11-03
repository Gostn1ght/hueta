//! Веб-установщик: маленький exe без встроенного лаунчера. При установке связывается с
//! сервером (P2P или HTTP-зеркало), проверяет подпись релиза, скачивает опубликованный
//! лаунчер, сверяет BLAKE3 и ставит его. Игру потом качает уже сам лаунчер.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[path = "../../../app/src/brand.rs"]
mod brand;
#[allow(dead_code)]
#[path = "../../../app/src/sys.rs"]
mod sys;

use anyhow::{anyhow, bail, Context, Result};
use brand::Brand;
use futures_util::StreamExt;
use gamesync::manifest::{LauncherRelease, Release};
use gamesync::util::{free_space, human_bytes};
use gamesync::Sources;
use parking_lot::Mutex;
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use tauri::{AppHandle, Emitter, WebviewUrl, WebviewWindowBuilder};

const VERSION: &str = env!("CARGO_PKG_VERSION");

struct St {
    brand: Brand,
    sources: Arc<Sources>,
    release: Mutex<Option<Release>>,
    connecting: tokio::sync::Mutex<()>,
}

type S<'a> = tauri::State<'a, Arc<St>>;

#[derive(Serialize)]
struct SetupInfo {
    product: String,
    title: String,
    version: String,
    default_dir: String,
    existing: bool,
    text: String,
}

#[tauri::command]
fn setup_info(st: S<'_>) -> SetupInfo {
    let b = &st.brand;
    let reg = sys::registered_location(&b.product);
    let existing = reg.as_ref().map(|p| p.join(".launcher").exists()).unwrap_or(false);
    let dir = reg.filter(|_| existing).unwrap_or_else(|| PathBuf::from(&b.default_install_dir));
    SetupInfo {
        product: b.product.clone(),
        title: b.title.clone(),
        version: VERSION.into(),
        default_dir: dir.to_string_lossy().into(),
        existing,
        text: b.setup_text.clone(),
    }
}

async fn ensure_release(st: &St) -> Result<Release> {
    let _g = st.connecting.lock().await;
    if let Some(r) = st.release.lock().clone() {
        return Ok(r);
    }
    if st.sources.has_p2p() && st.sources.node().is_none() {
        let node = gamesync::p2p::P2pNode::bind(None, 1, st.brand.p2p_hide_ip, &st.brand.p2p_relays).await?;
        st.sources.set_node(node);
    }
    let r = tokio::time::timeout(Duration::from_secs(30), gamesync::fetch_release(&st.sources, &st.brand.public_key))
        .await
        .map_err(|_| anyhow!("сервер не ответил за 30 с"))??;
    *st.release.lock() = Some(r.clone());
    Ok(r)
}

#[derive(Serialize)]
struct Connected {
    launcher_version: Option<String>,
    launcher_size: Option<u64>,
    game_version: String,
    game_size: u64,
}

#[tauri::command]
async fn connect(st: S<'_>) -> Result<Connected, String> {
    let r = ensure_release(&st).await.map_err(|e| format!("Сервер недоступен: {e:#}"))?;
    Ok(Connected {
        launcher_version: r.launcher.as_ref().map(|l| l.version.clone()),
        launcher_size: r.launcher.as_ref().map(|l| l.size),
        game_version: r.version,
        game_size: r.game_size,
    })
}

#[derive(Serialize)]
struct DirInfo {
    free: Option<u64>,
    free_text: String,
    has_game: bool,
    message: String,
}

#[tauri::command]
fn dir_info(st: S<'_>, path: String) -> DirInfo {
    let p = PathBuf::from(&path);
    let free = free_space(&p);
    let drive = p.components().next().map(|c| c.as_os_str().to_string_lossy().to_string()).unwrap_or_default();
    let has_game = p.join(".launcher").exists() || p.join(&st.brand.exe_name).exists();
    let non_empty = std::fs::read_dir(&p).map(|mut d| d.next().is_some()).unwrap_or(false);
    let message = if has_game {
        "Игра уже есть в этой папке — докачаются только изменения.".to_string()
    } else if non_empty {
        "Папка не пустая. Если в ней старая копия игры — лаунчер проверит её и докачает только недостающее.".to_string()
    } else {
        String::new()
    };
    DirInfo { free, free_text: free.map(|f| format!("Свободно на {drive} {}", human_bytes(f))).unwrap_or_default(), has_game, message }
}

#[tauri::command]
async fn pick_dir(current: String) -> Option<String> {
    tokio::task::spawn_blocking(move || {
        let mut d = rfd::FileDialog::new().set_title("Папка установки");
        if let Some(existing) = PathBuf::from(&current).ancestors().find(|a| a.is_dir()) {
            d = d.set_directory(existing);
        }
        d.pick_folder().map(|p| p.to_string_lossy().to_string())
    })
    .await
    .ok()
    .flatten()
}

#[derive(Serialize, Clone)]
struct Prog {
    text: String,
    done: u64,
    total: u64,
}

fn prog(app: &AppHandle, text: &str, done: u64, total: u64) {
    let _ = app.emit("setup-progress", Prog { text: text.into(), done, total });
}

/// Лаунчер кусками по 1 МБ с перебором зеркал — с прогрессом и повтором при обрыве.
async fn download(app: &AppHandle, src: &Sources, l: &LauncherRelease) -> Result<Vec<u8>> {
    const STEP: u64 = 1 << 20;
    let mut out = Vec::with_capacity(l.size as usize);
    let mut fails = 0u32;
    let mut mirror = 0usize;
    while (out.len() as u64) < l.size {
        let start = out.len() as u64;
        let end = (start + STEP).min(l.size);
        let r: Result<()> = async {
            let mut s = tokio::time::timeout(Duration::from_secs(30), src.range(mirror, &l.path, start, end))
                .await
                .map_err(|_| anyhow!("сервер не отвечает"))??;
            let mut got = 0u64;
            while got < end - start {
                let b = tokio::time::timeout(Duration::from_secs(30), s.next())
                    .await
                    .map_err(|_| anyhow!("нет данных 30 с"))?
                    .ok_or_else(|| anyhow!("сервер оборвал передачу"))??;
                let take = (b.len() as u64).min(end - start - got) as usize;
                out.extend_from_slice(&b[..take]);
                got += take as u64;
                prog(app, "Загрузка лаунчера", out.len() as u64, l.size);
            }
            Ok(())
        }
        .await;
        if let Err(e) = r {
            out.truncate(start as usize);
            fails += 1;
            mirror += 1;
            if fails > 8 {
                return Err(e.context("не удалось скачать лаунчер"));
            }
            tokio::time::sleep(Duration::from_millis(500 * fails as u64)).await;
        }
    }
    if hex::encode(blake3::hash(&out).as_bytes()) != l.hash {
        bail!("скачанный лаунчер повреждён (хеш не совпал) — попробуйте ещё раз");
    }
    Ok(out)
}

#[tauri::command]
async fn do_install(app: AppHandle, st: S<'_>, path: String, desktop: bool, start_menu: bool, launch: bool) -> Result<(), String> {
    let st = st.inner().clone();
    let r: Result<bool> = async {
        let dir = PathBuf::from(path.trim());
        if !dir.is_absolute() {
            bail!("Укажите полный путь к папке");
        }
        prog(&app, "Связь с сервером", 0, 0);
        let rel = ensure_release(&st).await.context("сервер недоступен")?;
        let l = rel.launcher.clone().context("На сервере ещё не опубликован лаунчер")?;
        std::fs::create_dir_all(dir.join(".launcher")).with_context(|| format!("не удалось создать {}", dir.display()))?;
        let target = dir.join(&st.brand.exe_name);
        let same = std::fs::read(&target).map(|b| hex::encode(blake3::hash(&b).as_bytes()) == l.hash).unwrap_or(false);
        if !same {
            let data = download(&app, &st.sources, &l).await?;
            prog(&app, "Установка", l.size, l.size);
            let tmp = target.with_extension("exe.new");
            std::fs::write(&tmp, &data)?;
            if target.exists() {
                let old = target.with_extension("exe.old");
                let _ = std::fs::remove_file(&old);
                std::fs::rename(&target, &old).map_err(|e| anyhow!("Закройте лаунчер и повторите ({e})"))?;
            }
            std::fs::rename(&tmp, &target)?;
        }
        install_files(&st.brand, &dir, &target, &l.version, desktop, start_menu)?;
        if launch {
            std::process::Command::new(&target).current_dir(&dir).spawn()?;
        }
        Ok(launch)
    }
    .await;
    match r {
        Ok(launched) => {
            if launched {
                tokio::time::sleep(Duration::from_millis(300)).await;
                app.exit(0);
            }
            Ok(())
        }
        Err(e) => Err(format!("{e:#}")),
    }
}

fn install_files(b: &Brand, dir: &Path, target: &Path, version: &str, desktop: bool, start_menu: bool) -> Result<()> {
    std::fs::write(
        dir.join(".launcher").join("install.json"),
        serde_json::to_vec_pretty(&serde_json::json!({
            "product": b.product,
            "launcher": version,
            "installed": gamesync::local::now_unix(),
            "setup": VERSION,
        }))?,
    )?;
    sys::register_uninstall(&b.product, &b.publisher, version, dir, target)?;
    if desktop {
        if let Some(l) = sys::desktop_lnk(&b.product) {
            sys::create_shortcut(&l, target, "", dir, &b.product)?;
        }
    }
    if start_menu {
        if let Some(d) = sys::start_menu_dir(&b.product) {
            sys::create_shortcut(&d.join(format!("{}.lnk", b.product)), target, "", dir, &b.product)?;
            sys::create_shortcut(&d.join(format!("Удалить {}.lnk", b.product)), target, "--uninstall", dir, "Удаление")?;
        }
    }
    Ok(())
}

#[tauri::command]
fn quit(app: AppHandle) {
    app.exit(0);
}

fn main() {
    let brand = brand::load();
    let sources = Arc::new(Sources::new(&brand.base_urls, Duration::from_secs(10)).expect("base_urls"));
    let title = format!("{} — установка", brand.product);
    tauri::Builder::default()
        .manage(Arc::new(St { brand, sources, release: Mutex::new(None), connecting: tokio::sync::Mutex::new(()) }))
        .invoke_handler(tauri::generate_handler![setup_info, connect, dir_info, pick_dir, do_install, quit])
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "setup", WebviewUrl::App("websetup.html".into()))
                .title(&title)
                .inner_size(880.0, 540.0)
                .resizable(false)
                .decorations(false)
                .center()
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("ошибка запуска окна");
}
