//! NetAnomalyServer — сервер раздачи игры без белого IP.
//!
//! * P2P-узел (iroh): отдаёт релиз (latest.json, манифест, pack-файлы, новости) и работает
//!   трекером — сообщает лаунчерам, какие игроки уже раздают нужную версию.
//! * Веб-панель на http://127.0.0.1:8787 (только с этого ПК): публикация версий, новости,
//!   игроки онлайн, трафик, настройки.
//! * По желанию — HTTP-зеркало (если появится белый IP или хостинг).

use anyhow::{anyhow, Context, Result};
use axum::extract::{Path as AxPath, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use gamesync::manifest::{safe_rel_path, Hash};
use gamesync::p2p::{ChunkData, EndpointId, P2pNode, Provider};
use gamesync::util::human_bytes;
use packer::{PackOptions, PackProgress, PackReport, StoreEntry};
use parking_lot::{Mutex, RwLock};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering::Relaxed;
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Serialize, Deserialize, Clone)]
struct Config {
    product: String,
    publish_dir: PathBuf,
    signing_key: PathBuf,
    panel_port: u16,
    /// 0 — HTTP-зеркало выключено.
    http_port: u16,
    upload_slots: usize,
    #[serde(default)]
    admin_salt: String,
    #[serde(default)]
    admin_hash: String,
    #[serde(default)]
    last_input: String,
    #[serde(default)]
    last_exclude: String,
    #[serde(default)]
    last_launcher: String,
    /// Не раскрывать IP сервера игрокам: только через relay.
    #[serde(default = "yes")]
    hide_ip: bool,
    /// relay-серверы (адреса https://…); пусто — список по умолчанию без недоступного euc1.
    #[serde(default = "gamesync::p2p::default_relays")]
    relays: Vec<String>,
}

fn yes() -> bool {
    true
}

struct PeerInfo {
    manifest_hash: String,
    version: String,
    first: Instant,
    last: Instant,
}

struct ServerProvider {
    publish: PathBuf,
    store: RwLock<HashMap<Hash, StoreEntry>>,
    tracker: Mutex<HashMap<EndpointId, PeerInfo>>,
}

const PEER_TTL: Duration = Duration::from_secs(180);

impl ServerProvider {
    fn reload(&self) {
        *self.store.write() = packer::load_store(&self.publish).chunks;
    }
}

impl Provider for ServerProvider {
    fn file(&self, path: &str) -> Option<PathBuf> {
        if !safe_rel_path(path) {
            return None;
        }
        let ok = path == "latest.json"
            || path == "news.json"
            || ["manifests/", "packs/", "news/", "launcher/"].iter().any(|p| path.starts_with(p));
        let p = self.publish.join(path);
        (ok && p.is_file()).then_some(p)
    }

    fn chunk(&self, hash: &Hash) -> Option<ChunkData> {
        let e = self.store.read().get(hash).cloned()?;
        let f = std::fs::File::open(self.publish.join(&e.pack)).ok()?;
        let mut buf = vec![0u8; e.csize as usize];
        gamesync::util::pread(&f, &mut buf, e.offset).ok()?;
        Some(if e.zstd { ChunkData::Zstd(buf) } else { ChunkData::Raw(buf) })
    }

    fn announce(&self, peer: EndpointId, manifest_hash: String, version: String) {
        let mut t = self.tracker.lock();
        let now = Instant::now();
        let first = t.get(&peer).map(|p| p.first).unwrap_or(now);
        t.insert(peer, PeerInfo { manifest_hash, version, first, last: now });
    }

    fn peers(&self, peer: EndpointId, manifest_hash: &str) -> Vec<String> {
        let mut t = self.tracker.lock();
        t.retain(|_, p| p.last.elapsed() < PEER_TTL);
        let mut v: Vec<(EndpointId, Instant)> =
            t.iter().filter(|(id, p)| **id != peer && p.manifest_hash == manifest_hash).map(|(id, p)| (*id, p.last)).collect();
        v.sort_by_key(|(_, l)| std::cmp::Reverse(*l));
        v.into_iter().take(30).map(|(id, _)| id.to_string()).collect()
    }
}

#[derive(Default, Serialize, Clone)]
struct Job {
    running: bool,
    version: String,
    progress: Option<PackProgress>,
    report: Option<PackReport>,
    error: Option<String>,
    started: u64,
}

struct App {
    data: PathBuf,
    cfg: Mutex<Config>,
    node: Arc<P2pNode>,
    prov: Arc<ServerProvider>,
    sessions: Mutex<HashMap<String, Instant>>,
    throttle: Mutex<Throttle>,
    job: Mutex<Job>,
    started: Instant,
    upload_speed: Mutex<f64>,
    online: Mutex<bool>,
}

type St = State<Arc<App>>;

fn rand_hex(n: usize) -> String {
    let mut b = vec![0u8; n];
    getrandom::getrandom(&mut b).expect("getrandom");
    hex::encode(b)
}

/// Пароль панели зашит в код в виде соли и медленного хеша (сам пароль в exe не хранится).
/// Владелец получил его отдельно (keys\\ADMIN_PASSWORD.txt). Сменить — только пересборкой.
const ADMIN_SALT: &str = "185066c638584f3e090efc6c3c4e6e82";
const ADMIN_HASH: &str = "534bd57d09783cd277397d41c651a1da0797bb98f5039e1714de3fb7e52de8d2";
const HASH_ROUNDS: u32 = 300_000;
const SESSION_TTL: Duration = Duration::from_secs(12 * 3600);
const MAX_FAILS_BEFORE_LOCK: u32 = 5;

fn hash_pw(salt: &str, pw: &str) -> [u8; 32] {
    let mut h = blake3::hash(format!("{salt}:{pw}").as_bytes());
    for _ in 0..HASH_ROUNDS {
        h = blake3::hash(h.as_bytes());
    }
    *h.as_bytes()
}

/// Сравнение за постоянное время: по длительности нельзя угадать совпавшие байты.
fn same(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

fn password_ok(pw: &str) -> bool {
    let Ok(want) = hex::decode(ADMIN_HASH) else { return false };
    pw.len() <= 256 && same(&hash_pw(ADMIN_SALT, pw), &want)
}

#[derive(Default)]
struct Throttle {
    fails: u32,
    locks: u32,
    locked_until: Option<Instant>,
}

impl App {
    fn save_cfg(&self) -> Result<()> {
        std::fs::write(self.data.join("config.json"), serde_json::to_vec_pretty(&*self.cfg.lock())?)?;
        Ok(())
    }

    fn authed(&self, h: &HeaderMap) -> bool {
        let Some(c) = h.get(header::COOKIE).and_then(|v| v.to_str().ok()) else { return false };
        let mut s = self.sessions.lock();
        s.retain(|_, t| t.elapsed() < SESSION_TTL);
        c.split(';').filter_map(|kv| kv.trim().strip_prefix("sid=")).any(|sid| s.contains_key(sid))
    }

    fn login(&self) -> String {
        let sid = rand_hex(32);
        self.sessions.lock().insert(sid.clone(), Instant::now());
        format!("sid={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={}", SESSION_TTL.as_secs())
    }

    fn news_path(&self) -> PathBuf {
        self.cfg.lock().publish_dir.join("news.json")
    }
}

fn err(code: StatusCode, msg: impl Into<String>) -> Response {
    (code, Json(json!({ "error": msg.into() }))).into_response()
}

macro_rules! auth {
    ($app:expr, $h:expr) => {
        if !$app.authed(&$h) {
            return err(StatusCode::UNAUTHORIZED, "нужен вход");
        }
    };
}

async fn index() -> Html<&'static str> {
    Html(include_str!("panel.html"))
}

async fn api_state(State(app): St, h: HeaderMap) -> Response {
    Json(json!({ "needs_setup": false, "logged_in": app.authed(&h) })).into_response()
}

#[derive(Deserialize)]
struct Pw {
    password: String,
}

async fn api_login(State(app): St, Json(b): Json<Pw>) -> Response {
    // Блокировка после серии ошибок: 5 неверных подряд — пауза 5 мин, дальше вдвое дольше, до часа.
    {
        let t = app.throttle.lock();
        if let Some(until) = t.locked_until {
            if Instant::now() < until {
                let left = (until - Instant::now()).as_secs() / 60 + 1;
                return err(StatusCode::TOO_MANY_REQUESTS, format!("слишком много неверных попыток, вход закрыт ещё на {left} мин"));
            }
        }
    }
    let pw = b.password;
    let ok = tokio::task::spawn_blocking(move || password_ok(&pw)).await.unwrap_or(false);
    if !ok {
        let delay = {
            let mut t = app.throttle.lock();
            t.fails += 1;
            if t.fails >= MAX_FAILS_BEFORE_LOCK {
                t.fails = 0;
                t.locks += 1;
                let mins = (5u64 << (t.locks - 1).min(4)).min(60);
                t.locked_until = Some(Instant::now() + Duration::from_secs(mins * 60));
                println!("Панель: {MAX_FAILS_BEFORE_LOCK} неверных паролей подряд — вход закрыт на {mins} мин");
            }
            Duration::from_millis(800 * t.fails.max(1) as u64)
        };
        tokio::time::sleep(delay).await;
        return err(StatusCode::UNAUTHORIZED, "неверный пароль");
    }
    *app.throttle.lock() = Throttle::default();
    ([(header::SET_COOKIE, app.login())], Json(json!({"ok": true}))).into_response()
}

async fn api_status(State(app): St, h: HeaderMap) -> Response {
    auth!(app, h);
    let cfg = app.cfg.lock().clone();
    let rel = packer::read_release(&cfg.publish_dir);
    let pubkey = std::fs::read_to_string(&cfg.signing_key)
        .ok()
        .and_then(|s| gamesync::sign::public_from_secret(&s).ok())
        .unwrap_or_default();
    let peers_online = {
        let t = app.prov.tracker.lock();
        let mh = rel.as_ref().map(|r| r.manifest_hash.clone()).unwrap_or_default();
        t.values().filter(|p| p.last.elapsed() < PEER_TTL && p.manifest_hash == mh).count()
    };
    let st = &app.node.stats;
    Json(json!({
        "product": cfg.product,
        "node_id": app.node.id().to_string(),
        "public_key": pubkey,
        "online": *app.online.lock(),
        "release": rel,
        "peers_online": peers_online,
        "sent": st.sent.load(Relaxed),
        "sent_text": human_bytes(st.sent.load(Relaxed)),
        "speed": *app.upload_speed.lock(),
        "active": st.active.load(Relaxed),
        "requests": st.requests.load(Relaxed),
        "uptime": app.started.elapsed().as_secs(),
        "http_port": cfg.http_port,
        "upload_slots": cfg.upload_slots,
        "hide_ip": cfg.hide_ip,
        "publish_dir": cfg.publish_dir,
        "last_input": cfg.last_input,
        "last_exclude": cfg.last_exclude,
        "last_launcher": cfg.last_launcher,
        "job": *app.job.lock(),
    }))
    .into_response()
}

#[derive(Deserialize)]
struct PublishReq {
    input: String,
    version: String,
    #[serde(default = "default_level")]
    level: i32,
    #[serde(default)]
    exclude: String,
    #[serde(default)]
    rescan: bool,
}

fn default_level() -> i32 {
    19
}

async fn api_publish(State(app): St, h: HeaderMap, Json(b): Json<PublishReq>) -> Response {
    auth!(app, h);
    let version = b.version.trim().to_string();
    if version.is_empty() || b.input.trim().is_empty() {
        return err(StatusCode::BAD_REQUEST, "укажите папку игры и версию");
    }
    {
        let mut j = app.job.lock();
        if j.running {
            return err(StatusCode::CONFLICT, "публикация уже идёт");
        }
        *j = Job { running: true, version: version.clone(), started: gamesync::local::now_unix(), ..Default::default() };
    }
    let (opts, key_path) = {
        let mut c = app.cfg.lock();
        c.last_input = b.input.trim().into();
        c.last_exclude = b.exclude.clone();
        let exclude: Vec<String> = b.exclude.split([',', '\n']).map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
        (
            PackOptions {
                input: PathBuf::from(b.input.trim()),
                out: c.publish_dir.clone(),
                version,
                secret_key: String::new(),
                product: c.product.clone(),
                level: b.level.clamp(1, 22),
                pack_size: 256 << 20,
                exclude,
                launcher: None,
                launcher_version: None,
                rescan: b.rescan,
            },
            c.signing_key.clone(),
        )
    };
    let _ = app.save_cfg();
    let app2 = app.clone();
    tokio::task::spawn_blocking(move || {
        let res = std::fs::read_to_string(&key_path)
            .map_err(|e| anyhow!("ключ подписи {}: {e}", key_path.display()))
            .and_then(|k| {
                let o = PackOptions { secret_key: k, ..opts };
                packer::pack(&o, &|p: &PackProgress| app2.job.lock().progress = Some(p.clone()))
            });
        let mut j = app2.job.lock();
        j.running = false;
        match res {
            Ok(r) => {
                println!("Опубликована версия {} ({} файлов, новых данных {})", r.version, r.files, human_bytes(r.new_bytes));
                j.report = Some(r);
                app2.prov.reload();
            }
            Err(e) => j.error = Some(format!("{e:#}")),
        }
    });
    Json(json!({"ok": true})).into_response()
}

#[derive(Deserialize)]
struct LauncherReq {
    exe: String,
    version: String,
}

async fn api_launcher(State(app): St, h: HeaderMap, Json(b): Json<LauncherReq>) -> Response {
    auth!(app, h);
    let (out, key) = {
        let mut c = app.cfg.lock();
        c.last_launcher = b.exe.trim().into();
        (c.publish_dir.clone(), c.signing_key.clone())
    };
    let _ = app.save_cfg();
    let (exe, version) = (PathBuf::from(b.exe.trim()), b.version.trim().to_string());
    let r = tokio::task::spawn_blocking(move || -> Result<gamesync::manifest::LauncherRelease> {
        let secret = std::fs::read_to_string(&key).map_err(|e| anyhow!("ключ подписи {}: {e}", key.display()))?;
        packer::publish_launcher(&out, &exe, &version, &secret)
    })
    .await;
    match r {
        Ok(Ok(l)) => {
            println!("Опубликован лаунчер {} ({})", l.version, human_bytes(l.size));
            Json(l).into_response()
        }
        Ok(Err(e)) => err(StatusCode::BAD_REQUEST, format!("{e:#}")),
        Err(e) => err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()),
    }
}

#[derive(Serialize, Deserialize, Clone, Default)]
struct NewsItem {
    #[serde(default)]
    id: String,
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

fn load_news(p: &Path) -> Vec<NewsItem> {
    let mut v: Vec<NewsItem> = std::fs::read(p).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default();
    for (i, n) in v.iter_mut().enumerate() {
        if n.id.is_empty() {
            n.id = format!("old{i}");
        }
    }
    v
}

fn save_news(p: &Path, v: &[NewsItem]) -> Result<()> {
    let tmp = p.with_extension("json.tmp");
    std::fs::write(&tmp, serde_json::to_vec_pretty(v)?)?;
    std::fs::rename(&tmp, p)?;
    Ok(())
}

async fn api_news(State(app): St, h: HeaderMap) -> Response {
    auth!(app, h);
    Json(load_news(&app.news_path())).into_response()
}

#[derive(Deserialize)]
struct NewsReq {
    #[serde(default)]
    id: String,
    title: String,
    #[serde(default)]
    date: String,
    #[serde(default)]
    text: String,
    #[serde(default)]
    link: String,
    /// data:image/...;base64,... — новая картинка
    #[serde(default)]
    image_data: String,
    #[serde(default)]
    remove_image: bool,
}

async fn api_news_save(State(app): St, h: HeaderMap, Json(b): Json<NewsReq>) -> Response {
    auth!(app, h);
    let r = (|| -> Result<NewsItem> {
        if b.title.trim().is_empty() {
            anyhow::bail!("нужен заголовок");
        }
        if !b.link.is_empty() && !(b.link.starts_with("https://") || b.link.starts_with("http://")) {
            anyhow::bail!("ссылка должна начинаться с https://");
        }
        let path = app.news_path();
        let mut list = load_news(&path);
        let id = if b.id.is_empty() { format!("{:x}", gamesync::local::now_unix()) + &rand_hex(2) } else { b.id.clone() };
        let mut item = list.iter().find(|n| n.id == id).cloned().unwrap_or_default();
        item.id = id.clone();
        item.title = b.title.trim().into();
        item.text = b.text.trim().into();
        item.link = b.link.trim().into();
        item.date = if b.date.trim().is_empty() { today() } else { b.date.trim().into() };
        if b.remove_image {
            item.image.clear();
        }
        if let Some(rest) = b.image_data.strip_prefix("data:") {
            use base64::Engine;
            let (mime, data) = rest.split_once(";base64,").context("картинка повреждена")?;
            let ext = match mime {
                "image/png" => "png",
                "image/jpeg" => "jpg",
                "image/webp" => "webp",
                "image/gif" => "gif",
                _ => anyhow::bail!("картинка должна быть png/jpg/webp/gif"),
            };
            let bytes = base64::engine::general_purpose::STANDARD.decode(data)?;
            if bytes.len() > 3 << 20 {
                anyhow::bail!("картинка больше 3 МБ");
            }
            let dir = app.cfg.lock().publish_dir.join("news");
            std::fs::create_dir_all(&dir)?;
            let name = format!("{id}-{}.{ext}", rand_hex(3));
            std::fs::write(dir.join(&name), bytes)?;
            item.image = format!("news/{name}");
        }
        match list.iter_mut().find(|n| n.id == id) {
            Some(n) => *n = item.clone(),
            None => list.insert(0, item.clone()),
        }
        save_news(&path, &list)?;
        Ok(item)
    })();
    match r {
        Ok(i) => Json(i).into_response(),
        Err(e) => err(StatusCode::BAD_REQUEST, format!("{e:#}")),
    }
}

async fn api_news_delete(State(app): St, h: HeaderMap, AxPath(id): AxPath<String>) -> Response {
    auth!(app, h);
    let path = app.news_path();
    let mut list = load_news(&path);
    list.retain(|n| n.id != id);
    match save_news(&path, &list) {
        Ok(()) => Json(json!({"ok": true})).into_response(),
        Err(e) => err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()),
    }
}

async fn news_image(State(app): St, h: HeaderMap, AxPath(name): AxPath<String>) -> Response {
    auth!(app, h);
    if !safe_rel_path(&name) || name.contains('/') {
        return err(StatusCode::NOT_FOUND, "нет файла");
    }
    let p = app.cfg.lock().publish_dir.join("news").join(&name);
    let ct = match p.extension().and_then(|e| e.to_str()).unwrap_or("") {
        "png" => "image/png",
        "webp" => "image/webp",
        "gif" => "image/gif",
        _ => "image/jpeg",
    };
    match tokio::fs::read(&p).await {
        Ok(b) => ([(header::CONTENT_TYPE, ct)], b).into_response(),
        Err(_) => err(StatusCode::NOT_FOUND, "нет файла"),
    }
}

async fn api_peers(State(app): St, h: HeaderMap) -> Response {
    auth!(app, h);
    let t = app.prov.tracker.lock();
    let mut v: Vec<_> = t
        .iter()
        .filter(|(_, p)| p.last.elapsed() < PEER_TTL)
        .map(|(id, p)| json!({ "id": id.fmt_short().to_string(), "version": p.version, "seen": p.last.elapsed().as_secs(), "online_for": p.first.elapsed().as_secs() }))
        .collect();
    v.sort_by_key(|x| x["seen"].as_u64().unwrap_or(0));
    Json(v).into_response()
}

#[derive(Deserialize)]
struct SettingsReq {
    product: String,
    http_port: u16,
    upload_slots: usize,
    #[serde(default = "yes")]
    hide_ip: bool,
}

async fn api_settings(State(app): St, h: HeaderMap, Json(b): Json<SettingsReq>) -> Response {
    auth!(app, h);
    {
        let mut c = app.cfg.lock();
        c.product = b.product.trim().into();
        c.http_port = b.http_port;
        c.upload_slots = b.upload_slots.clamp(1, 64);
        c.hide_ip = b.hide_ip;
    }
    match app.save_cfg() {
        Ok(()) => Json(json!({"ok": true, "restart": true})).into_response(),
        Err(e) => err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()),
    }
}

fn today() -> String {
    // Без внешних зависимостей: дата по UTC (для заголовка новости этого достаточно).
    let days = (gamesync::local::now_unix() / 86400) as i64;
    let (y, m, d) = civil_from_days(days);
    format!("{d:02}.{m:02}.{y}")
}

fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

fn load_config(data: &Path) -> Result<Config> {
    let p = data.join("config.json");
    if let Ok(b) = std::fs::read(&p) {
        let mut c: Config = serde_json::from_slice(&b).with_context(|| format!("{} повреждён", p.display()))?;
        if c.publish_dir.as_os_str().is_empty() {
            c.publish_dir = data.join("publish");
        }
        if c.signing_key.as_os_str().is_empty() {
            c.signing_key = data.join("keys").join("secret.key");
        }
        if c.panel_port == 0 {
            c.panel_port = 8787;
        }
        if c.upload_slots == 0 {
            c.upload_slots = 16;
        }
        return Ok(c);
    }
    let c = Config {
        product: "NetAnomaly".into(),
        publish_dir: data.join("publish"),
        signing_key: data.join("keys").join("secret.key"),
        panel_port: 8787,
        http_port: 0,
        upload_slots: 16,
        admin_salt: String::new(),
        admin_hash: String::new(),
        last_input: String::new(),
        last_exclude: "_client_/**".into(),
        last_launcher: String::new(),
        hide_ip: true,
        relays: gamesync::p2p::default_relays(),
    };
    std::fs::create_dir_all(data)?;
    std::fs::write(&p, serde_json::to_vec_pretty(&c)?)?;
    Ok(c)
}

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let exe_dir = std::env::current_exe()?.parent().map(Path::to_path_buf).unwrap_or_default();
    let data = args.iter().position(|a| a == "--data").and_then(|i| args.get(i + 1)).map(PathBuf::from).unwrap_or(exe_dir.join("server_data"));
    let no_browser = args.iter().any(|a| a == "--no-browser");
    // Диагностика сети: RUST_LOG=iroh=debug NetAnomalyServer.exe
    if std::env::var_os("RUST_LOG").is_some() {
        let _ = tracing_subscriber::fmt().with_env_filter(tracing_subscriber::EnvFilter::from_default_env()).with_writer(std::io::stderr).try_init();
    }

    let cfg = load_config(&data)?;
    std::fs::create_dir_all(&cfg.publish_dir)?;
    if !cfg.signing_key.exists() {
        let pk = packer::keygen(cfg.signing_key.parent().unwrap_or(Path::new(".")))?;
        println!("Создан ключ подписи релизов. public_key: {pk}");
    }

    println!("Запуск P2P-узла…");
    let node = P2pNode::bind(Some(&data.join("node.key")), cfg.upload_slots, cfg.hide_ip, &cfg.relays).await?;
    let prov = Arc::new(ServerProvider { publish: cfg.publish_dir.clone(), store: RwLock::new(HashMap::new()), tracker: Mutex::new(HashMap::new()) });
    prov.reload();
    node.set_provider(Some(prov.clone()));
    let id = node.id();

    let app = Arc::new(App {
        data: data.clone(),
        cfg: Mutex::new(cfg.clone()),
        node: node.clone(),
        prov,
        sessions: Mutex::new(HashMap::new()),
        throttle: Mutex::new(Throttle::default()),
        job: Mutex::new(Job::default()),
        started: Instant::now(),
        upload_speed: Mutex::new(0.0),
        online: Mutex::new(false),
    });

    {
        let app = app.clone();
        tokio::spawn(async move {
            let online = app.node.online(Duration::from_secs(30)).await;
            *app.online.lock() = online;
            println!("{}", if online { "P2P: на связи (relay подключён), игроки могут подключаться" } else { "P2P: нет связи с relay — проверьте интернет" });
            let mut last = app.node.stats.sent.load(Relaxed);
            loop {
                tokio::time::sleep(Duration::from_secs(1)).await;
                let now = app.node.stats.sent.load(Relaxed);
                let mut s = app.upload_speed.lock();
                *s = *s * 0.7 + (now.saturating_sub(last)) as f64 * 0.3;
                last = now;
            }
        });
    }

    if cfg.http_port != 0 {
        let dir = cfg.publish_dir.clone();
        let port = cfg.http_port;
        tokio::spawn(async move {
            let r = Router::new().fallback_service(tower_http::services::ServeDir::new(&dir));
            match tokio::net::TcpListener::bind(("0.0.0.0", port)).await {
                Ok(l) => {
                    println!("HTTP-зеркало: порт {port}");
                    let _ = axum::serve(l, r).await;
                }
                Err(e) => println!("HTTP-зеркало не запустилось на порту {port}: {e}"),
            }
        });
    }

    let routes = Router::new()
        .route("/", get(index))
        .route("/api/state", get(api_state))
        .route("/api/login", post(api_login))
        .route("/api/status", get(api_status))
        .route("/api/publish", post(api_publish))
        .route("/api/launcher", post(api_launcher))
        .route("/api/news", get(api_news).post(api_news_save))
        .route("/api/news/{id}", delete(api_news_delete))
        .route("/api/peers", get(api_peers))
        .route("/news/{name}", get(news_image))
        .route("/api/settings", post(api_settings))
        .layer(axum::extract::DefaultBodyLimit::max(8 << 20))
        .with_state(app.clone());
    let panel = format!("http://127.0.0.1:{}/", cfg.panel_port);
    let l = tokio::net::TcpListener::bind(("127.0.0.1", cfg.panel_port)).await.with_context(|| format!("порт панели {} занят", cfg.panel_port))?;

    println!();
    println!("  {} — сервер раздачи", cfg.product);
    println!("  Адрес для лаунчера:  p2p://{id}");
    println!("  Панель управления:   {panel}");
    println!("  Папка релиза:        {}", cfg.publish_dir.display());
    println!("  IP сервера:          {}", if cfg.hide_ip { "скрыт (только через relay)" } else { "виден игрокам (прямые соединения)" });
    println!("  Закройте окно, чтобы остановить сервер.");
    println!();
    if !no_browser {
        let _ = std::process::Command::new("explorer").arg(&panel).spawn();
    }

    tokio::select! {
        r = axum::serve(l, routes) => r?,
        _ = tokio::signal::ctrl_c() => {}
    }
    node.shutdown().await;
    Ok(())
}
