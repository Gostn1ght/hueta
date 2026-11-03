//! P2P-транспорт на iroh: соединение по публичному ключу узла, без белого IP.
//! iroh пробивает NAT напрямую (hole punching), а если не вышло — гонит трафик через relay.
//!
//! Один протокол для сервера и игроков. Запрос: u32 длина + JSON. Ответ: u8 статус
//! (0 — ок, 1 — ошибка + u32 длина + текст), дальше данные по типу запроса.

use crate::manifest::{Hash, Manifest, Span};
use anyhow::{anyhow, bail, Context, Result};
use bytes::Bytes;
use futures_util::stream::{self, StreamExt};
use parking_lot::RwLock;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering::Relaxed};
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncSeekExt, AsyncWriteExt};

pub use iroh;
use iroh::endpoint::{presets, Connection, RecvStream, SendStream};
use iroh::protocol::{AcceptError, ProtocolHandler, Router};
use iroh::{Endpoint, SecretKey};
pub use iroh::EndpointId;

pub const ALPN: &[u8] = b"netanomaly/dist/1";

/// Ретрансляторы по умолчанию: публичные relay n0 без европейского euc1 — из России до него
/// TLS не проходит, а iroh по пингу выбирает его домашним и остаётся без связи.
pub const DEFAULT_RELAYS: &[&str] = &[
    "https://use1-1.relay.n0.iroh.link/",
    "https://usw1-1.relay.n0.iroh.link/",
    "https://aps1-1.relay.n0.iroh.link/",
];

pub fn default_relays() -> Vec<String> {
    DEFAULT_RELAYS.iter().map(|s| s.to_string()).collect()
}
const MAX_REQ: u32 = 1 << 20;
const MAX_CHUNKS_PER_REQ: usize = 512;

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "t")]
pub enum Req {
    File { path: String },
    Range { path: String, start: u64, end: u64 },
    Chunks { hashes: Vec<String> },
    Announce { manifest_hash: String, version: String },
    Peers { manifest_hash: String },
}

pub enum ChunkData {
    Raw(Vec<u8>),
    Zstd(Vec<u8>),
}

/// Что узел умеет отдавать. Сервер — файлы релиза, чанки из pack-файлов и трекер.
/// Лаунчер игрока — только чанки из установленной игры.
pub trait Provider: Send + Sync + 'static {
    fn file(&self, _path: &str) -> Option<PathBuf> {
        None
    }
    fn chunk(&self, _hash: &Hash) -> Option<ChunkData> {
        None
    }
    fn announce(&self, _peer: EndpointId, _manifest_hash: String, _version: String) {}
    fn peers(&self, _peer: EndpointId, _manifest_hash: &str) -> Vec<String> {
        vec![]
    }
}

#[derive(Default)]
pub struct Stats {
    pub sent: AtomicU64,
    pub received: AtomicU64,
    pub active: AtomicUsize,
    pub requests: AtomicU64,
}

pub fn parse_id(s: &str) -> Result<EndpointId> {
    EndpointId::from_str(s.trim()).map_err(|e| anyhow!("неверный P2P-адрес {s}: {e}"))
}

fn load_or_create_key(path: Option<&Path>) -> Result<SecretKey> {
    let Some(path) = path else { return Ok(SecretKey::generate()) };
    if let Ok(s) = std::fs::read_to_string(path) {
        let b: [u8; 32] = hex::decode(s.trim())?.try_into().map_err(|_| anyhow!("ключ узла повреждён"))?;
        return Ok(SecretKey::from_bytes(&b));
    }
    let k = SecretKey::generate();
    if let Some(p) = path.parent() {
        std::fs::create_dir_all(p)?;
    }
    std::fs::write(path, hex::encode(k.to_bytes()))?;
    Ok(k)
}

#[derive(Clone)]
struct Handler {
    provider: Arc<RwLock<Option<Arc<dyn Provider>>>>,
    stats: Arc<Stats>,
    slots: Arc<tokio::sync::Semaphore>,
}

impl std::fmt::Debug for Handler {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("netanomaly-dist")
    }
}

impl ProtocolHandler for Handler {
    async fn accept(&self, conn: Connection) -> Result<(), AcceptError> {
        let peer = conn.remote_id();
        while let Ok((send, recv)) = conn.accept_bi().await {
            let h = self.clone();
            tokio::spawn(async move {
                h.stats.active.fetch_add(1, Relaxed);
                let _ = h.serve(peer, send, recv).await;
                h.stats.active.fetch_sub(1, Relaxed);
            });
        }
        Ok(())
    }
}

async fn write_err(send: &mut SendStream, msg: &str) -> Result<()> {
    AsyncWriteExt::write_all(send, &[1u8]).await?;
    AsyncWriteExt::write_all(send, &(msg.len() as u32).to_le_bytes()).await?;
    AsyncWriteExt::write_all(send, msg.as_bytes()).await?;
    Ok(())
}

impl Handler {
    async fn serve(&self, peer: EndpointId, mut send: SendStream, mut recv: RecvStream) -> Result<()> {
        let len = AsyncReadExt::read_u32_le(&mut recv).await?;
        if len > MAX_REQ {
            bail!("слишком большой запрос");
        }
        let mut b = vec![0u8; len as usize];
        AsyncReadExt::read_exact(&mut recv, &mut b).await?;
        let req: Req = serde_json::from_slice(&b)?;
        self.stats.requests.fetch_add(1, Relaxed);
        let provider = self.provider.read().clone();
        let Some(provider) = provider else {
            write_err(&mut send, "узел ничего не раздаёт").await?;
            let _ = send.finish();
            return Ok(());
        };
        match req {
            Req::File { path } => match provider.file(&path) {
                Some(p) => {
                    let data = tokio::fs::read(&p).await?;
                    AsyncWriteExt::write_all(&mut send, &[0u8]).await?;
                    AsyncWriteExt::write_all(&mut send, &(data.len() as u64).to_le_bytes()).await?;
                    AsyncWriteExt::write_all(&mut send, &data).await?;
                    self.stats.sent.fetch_add(data.len() as u64, Relaxed);
                }
                None => write_err(&mut send, &format!("нет файла {path}")).await?,
            },
            Req::Range { path, start, end } => match provider.file(&path) {
                Some(p) if end > start => {
                    let mut f = tokio::fs::File::open(&p).await?;
                    let flen = f.metadata().await?.len();
                    if end > flen {
                        write_err(&mut send, "диапазон за концом файла").await?;
                    } else {
                        f.seek(std::io::SeekFrom::Start(start)).await?;
                        AsyncWriteExt::write_all(&mut send, &[0u8]).await?;
                        AsyncWriteExt::write_all(&mut send, &(end - start).to_le_bytes()).await?;
                        let mut left = end - start;
                        let mut buf = vec![0u8; 256 << 10];
                        while left > 0 {
                            let n = left.min(buf.len() as u64) as usize;
                            AsyncReadExt::read_exact(&mut f, &mut buf[..n]).await?;
                            AsyncWriteExt::write_all(&mut send, &buf[..n]).await?;
                            self.stats.sent.fetch_add(n as u64, Relaxed);
                            left -= n as u64;
                        }
                    }
                }
                _ => write_err(&mut send, &format!("нет файла {path}")).await?,
            },
            Req::Chunks { hashes } => {
                if hashes.len() > MAX_CHUNKS_PER_REQ {
                    write_err(&mut send, "слишком много чанков в запросе").await?;
                } else {
                    let _slot = self.slots.acquire().await?;
                    AsyncWriteExt::write_all(&mut send, &[0u8]).await?;
                    for h in hashes {
                        let hash: Option<Hash> = hex::decode(&h).ok().and_then(|v| v.try_into().ok());
                        let p = provider.clone();
                        let data = match hash {
                            Some(hash) => tokio::task::spawn_blocking(move || p.chunk(&hash)).await.ok().flatten(),
                            None => None,
                        };
                        let (kind, bytes) = match data {
                            None => (0u8, Vec::new()),
                            Some(ChunkData::Raw(d)) => (1u8, d),
                            Some(ChunkData::Zstd(d)) => (2u8, d),
                        };
                        AsyncWriteExt::write_all(&mut send, &[kind]).await?;
                        AsyncWriteExt::write_all(&mut send, &(bytes.len() as u32).to_le_bytes()).await?;
                        AsyncWriteExt::write_all(&mut send, &bytes).await?;
                        self.stats.sent.fetch_add(bytes.len() as u64, Relaxed);
                    }
                }
            }
            Req::Announce { manifest_hash, version } => {
                provider.announce(peer, manifest_hash, version);
                AsyncWriteExt::write_all(&mut send, &[0u8]).await?;
            }
            Req::Peers { manifest_hash } => {
                let list = serde_json::to_vec(&provider.peers(peer, &manifest_hash))?;
                AsyncWriteExt::write_all(&mut send, &[0u8]).await?;
                AsyncWriteExt::write_all(&mut send, &(list.len() as u32).to_le_bytes()).await?;
                AsyncWriteExt::write_all(&mut send, &list).await?;
            }
        }
        send.finish()?;
        // Дать данным уйти до закрытия потока.
        let _ = tokio::time::timeout(Duration::from_secs(30), send.stopped()).await;
        Ok(())
    }
}

/// P2P-узел: и клиент (качает), и раздающий (если задан Provider).
pub struct P2pNode {
    router: Router,
    conns: tokio::sync::Mutex<HashMap<EndpointId, Connection>>,
    provider: Arc<RwLock<Option<Arc<dyn Provider>>>>,
    pub stats: Arc<Stats>,
}

impl P2pNode {
    /// `key_file` — постоянный ключ (адрес узла не меняется между запусками).
    /// `upload_slots` — сколько запросов чанков обслуживать одновременно.
    /// `hide_ip` — без прямых соединений: весь трафик через relay, собеседник не узнаёт IP.
    /// (В DNS-публикации адреса iroh и так кладёт только relay, без IP.)
    /// `relays` — свои relay-серверы (пусто — встроенные n0 по умолчанию iroh).
    pub async fn bind(key_file: Option<&Path>, upload_slots: usize, hide_ip: bool, relays: &[String]) -> Result<Arc<Self>> {
        let sk = load_or_create_key(key_file)?;
        // Если в окружении задан HTTPS_PROXY (сеть, где программы выходят в интернет только через
        // VPN-прокси), iroh ходит к relay через него.
        let mut b = Endpoint::builder(presets::N0).secret_key(sk).proxy_from_env();
        if !relays.is_empty() {
            let urls = relays
                .iter()
                .map(|u| iroh::RelayUrl::from_str(u.trim()).map_err(|e| anyhow!("неверный адрес relay {u}: {e}")))
                .collect::<Result<Vec<_>>>()?;
            b = b.relay_mode(iroh::RelayMode::Custom(iroh::RelayMap::from_iter(urls)));
        }
        if hide_ip {
            b = b.clear_ip_transports();
        }
        let ep = b.bind().await.map_err(|e| anyhow!("не удалось запустить P2P: {e}"))?;
        let provider: Arc<RwLock<Option<Arc<dyn Provider>>>> = Arc::new(RwLock::new(None));
        let stats = Arc::new(Stats::default());
        let handler = Handler { provider: provider.clone(), stats: stats.clone(), slots: Arc::new(tokio::sync::Semaphore::new(upload_slots.max(1))) };
        let router = Router::builder(ep).accept(ALPN, handler).spawn();
        Ok(Arc::new(Self { router, conns: tokio::sync::Mutex::new(HashMap::new()), provider, stats }))
    }

    pub fn endpoint(&self) -> &Endpoint {
        self.router.endpoint()
    }

    pub fn id(&self) -> EndpointId {
        self.endpoint().id()
    }

    /// Дождаться подключения к relay (узел стал доступен из интернета).
    pub async fn online(&self, timeout: Duration) -> bool {
        tokio::time::timeout(timeout, self.endpoint().online()).await.is_ok()
    }

    pub fn set_provider(&self, p: Option<Arc<dyn Provider>>) {
        *self.provider.write() = p;
    }

    pub fn is_providing(&self) -> bool {
        self.provider.read().is_some()
    }

    pub async fn shutdown(&self) {
        let _ = self.router.shutdown().await;
    }

    async fn connection(&self, id: EndpointId) -> Result<Connection> {
        {
            let c = self.conns.lock().await;
            if let Some(c) = c.get(&id) {
                if c.close_reason().is_none() {
                    return Ok(c.clone());
                }
            }
        }
        let c = tokio::time::timeout(Duration::from_secs(25), self.endpoint().connect(id, ALPN))
            .await
            .map_err(|_| anyhow!("узел {} не отвечает", id.fmt_short()))?
            .map_err(|e| anyhow!("нет связи с узлом {}: {e}", id.fmt_short()))?;
        self.conns.lock().await.insert(id, c.clone());
        Ok(c)
    }

    async fn open(&self, id: EndpointId, req: &Req) -> Result<RecvStream> {
        let mut last = anyhow!("нет связи");
        for attempt in 0..2 {
            let c = self.connection(id).await?;
            match c.open_bi().await {
                Ok((mut s, mut r)) => {
                    let j = serde_json::to_vec(req)?;
                    AsyncWriteExt::write_all(&mut s, &(j.len() as u32).to_le_bytes()).await?;
                    AsyncWriteExt::write_all(&mut s, &j).await?;
                    s.finish()?;
                    let st = AsyncReadExt::read_u8(&mut r).await.context("узел закрыл поток")?;
                    if st != 0 {
                        let n = AsyncReadExt::read_u32_le(&mut r).await?.min(4096);
                        let mut m = vec![0u8; n as usize];
                        AsyncReadExt::read_exact(&mut r, &mut m).await?;
                        bail!("{}", String::from_utf8_lossy(&m));
                    }
                    return Ok(r);
                }
                Err(e) => {
                    last = anyhow!("{e}");
                    self.conns.lock().await.remove(&id);
                    if attempt == 1 {
                        break;
                    }
                }
            }
        }
        Err(last)
    }

    pub async fn get_file(&self, id: EndpointId, path: &str, max: u64) -> Result<Vec<u8>> {
        let mut r = self.open(id, &Req::File { path: path.into() }).await?;
        let n = AsyncReadExt::read_u64_le(&mut r).await?;
        if n > max {
            bail!("{path}: файл слишком большой");
        }
        let mut b = vec![0u8; n as usize];
        AsyncReadExt::read_exact(&mut r, &mut b).await?;
        self.stats.received.fetch_add(n, Relaxed);
        Ok(b)
    }

    pub async fn range(&self, id: EndpointId, path: &str, start: u64, end: u64) -> Result<crate::source::ByteStream> {
        let mut r = self.open(id, &Req::Range { path: path.into(), start, end }).await?;
        let n = AsyncReadExt::read_u64_le(&mut r).await?;
        if n != end - start {
            bail!("узел вернул не тот диапазон");
        }
        let stats = self.stats.clone();
        let s = stream::unfold((r, n, stats), |(mut r, left, stats)| async move {
            if left == 0 {
                return None;
            }
            let mut buf = vec![0u8; left.min(256 << 10) as usize];
            match AsyncReadExt::read(&mut r, &mut buf).await {
                Ok(0) => Some((Err(anyhow!("узел оборвал передачу")), (r, 0, stats))),
                Ok(k) => {
                    buf.truncate(k);
                    stats.received.fetch_add(k as u64, Relaxed);
                    Some((Ok(Bytes::from(buf)), (r, left - k as u64, stats)))
                }
                Err(e) => Some((Err(e.into()), (r, 0, stats))),
            }
        });
        Ok(s.boxed())
    }

    /// Запросить чанки по хешам. Кадры читать через [`read_chunk_frame`].
    pub async fn chunks(&self, id: EndpointId, hashes: &[Hash]) -> Result<RecvStream> {
        self.open(id, &Req::Chunks { hashes: hashes.iter().map(hex::encode).collect() }).await
    }

    pub async fn announce(&self, server: EndpointId, manifest_hash: &str, version: &str) -> Result<()> {
        self.open(server, &Req::Announce { manifest_hash: manifest_hash.into(), version: version.into() }).await?;
        Ok(())
    }

    pub async fn peers(&self, server: EndpointId, manifest_hash: &str) -> Result<Vec<EndpointId>> {
        let mut r = self.open(server, &Req::Peers { manifest_hash: manifest_hash.into() }).await?;
        let n = AsyncReadExt::read_u32_le(&mut r).await?.min(1 << 20);
        let mut b = vec![0u8; n as usize];
        AsyncReadExt::read_exact(&mut r, &mut b).await?;
        let list: Vec<String> = serde_json::from_slice(&b)?;
        Ok(list.iter().filter_map(|s| parse_id(s).ok()).filter(|p| *p != self.id()).collect())
    }
}

/// Один кадр ответа на Chunks: (0 — нет, 1 — как есть, 2 — zstd; данные).
pub async fn read_chunk_frame<R: AsyncRead + Unpin>(r: &mut R, max: u32) -> Result<(u8, Vec<u8>)> {
    let kind = r.read_u8().await?;
    let n = r.read_u32_le().await?;
    if n > max {
        bail!("кадр чанка слишком большой");
    }
    let mut b = vec![0u8; n as usize];
    r.read_exact(&mut b).await?;
    Ok((kind, b))
}

/// Раздача установленной игры другим игрокам: чанк по хешу → кусок файла на диске.
pub struct SeedIndex {
    map: HashMap<Hash, (PathBuf, u64, u32)>,
    pub manifest_hash: String,
    pub version: String,
}

impl SeedIndex {
    /// Только файлы, которые лаунчер проверил и которые с тех пор не менялись.
    pub fn build(dir: &Path) -> Option<Self> {
        let local = crate::local::Local::new(dir);
        let inst = local.installed()?;
        let m: Manifest = local.load_manifest()?;
        let idx = local.load_index();
        let mut map = HashMap::new();
        for f in &m.files {
            if crate::policy::is_never_distributed(&f.path) {
                continue;
            }
            let p = dir.join(&f.path);
            let ok = match (std::fs::metadata(&p), idx.files.get(&f.path)) {
                (Ok(meta), Some(e)) => meta.len() == f.size && e.hash == f.hash && e.mtime == crate::local::mtime_of(&meta),
                _ => false,
            };
            if ok {
                for Span { offset, size, hash, .. } in m.spans(f) {
                    map.entry(hash).or_insert_with(|| (p.clone(), offset, size));
                }
            }
        }
        Some(Self { map, manifest_hash: inst.manifest_hash, version: inst.version })
    }

    pub fn chunks(&self) -> usize {
        self.map.len()
    }
}

impl Provider for SeedIndex {
    fn chunk(&self, hash: &Hash) -> Option<ChunkData> {
        let (p, off, size) = self.map.get(hash)?;
        let f = std::fs::File::open(p).ok()?;
        let mut buf = vec![0u8; *size as usize];
        crate::util::pread(&f, &mut buf, *off).ok()?;
        if blake3::hash(&buf).as_bytes() != hash {
            return None; // файл изменился — не раздаём мусор
        }
        match zstd::bulk::compress(&buf, 1) {
            Ok(c) if c.len() < buf.len() * 95 / 100 => Some(ChunkData::Zstd(c)),
            _ => Some(ChunkData::Raw(buf)),
        }
    }
}
