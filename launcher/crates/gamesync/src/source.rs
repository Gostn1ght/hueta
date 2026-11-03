//! Источники данных: HTTP(S)-зеркала (Range-запросы) и локальные папки (file:///).

use anyhow::{anyhow, bail, Result};
use bytes::Bytes;
use futures_util::stream::{self, BoxStream, StreamExt};
use std::io::SeekFrom;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncSeekExt};

#[derive(Clone, Debug)]
pub enum Mirror {
    Http(String),
    Local(PathBuf),
    /// `p2p://<ключ узла>` — сервер раздачи без белого IP.
    P2p(crate::p2p::EndpointId),
}

impl Mirror {
    pub fn parse(u: &str) -> Mirror {
        let u = u.trim();
        if let Some(id) = u.strip_prefix("p2p://") {
            if let Ok(id) = crate::p2p::parse_id(id.trim_end_matches('/')) {
                return Mirror::P2p(id);
            }
        }
        if u.starts_with("http://") || u.starts_with("https://") {
            let mut s = u.to_string();
            if !s.ends_with('/') {
                s.push('/');
            }
            Mirror::Http(s)
        } else if let Some(p) = u.strip_prefix("file:///") {
            Mirror::Local(PathBuf::from(p))
        } else {
            Mirror::Local(PathBuf::from(u))
        }
    }
}

pub struct Sources {
    pub mirrors: Vec<Mirror>,
    client: reqwest::Client,
    rr: AtomicUsize,
    node: std::sync::OnceLock<std::sync::Arc<crate::p2p::P2pNode>>,
}

pub type ByteStream = BoxStream<'static, Result<Bytes>>;

impl Sources {
    pub fn new(urls: &[String], connect_timeout: Duration) -> Result<Self> {
        if urls.is_empty() {
            bail!("не задан ни один адрес сервера");
        }
        let client = reqwest::Client::builder()
            .connect_timeout(connect_timeout)
            .pool_max_idle_per_host(64)
            .tcp_nodelay(true)
            .http1_only()
            .user_agent(concat!("gamesync/", env!("CARGO_PKG_VERSION")))
            .build()?;
        Ok(Self { mirrors: urls.iter().map(|u| Mirror::parse(u)).collect(), client, rr: AtomicUsize::new(0), node: std::sync::OnceLock::new() })
    }

    pub fn len(&self) -> usize {
        self.mirrors.len()
    }

    pub fn set_node(&self, node: std::sync::Arc<crate::p2p::P2pNode>) {
        let _ = self.node.set(node);
    }

    pub fn node(&self) -> Option<&std::sync::Arc<crate::p2p::P2pNode>> {
        self.node.get()
    }

    pub fn has_p2p(&self) -> bool {
        self.mirrors.iter().any(|m| matches!(m, Mirror::P2p(_)))
    }

    pub fn p2p_servers(&self) -> Vec<crate::p2p::EndpointId> {
        self.mirrors.iter().filter_map(|m| if let Mirror::P2p(id) = m { Some(*id) } else { None }).collect()
    }

    fn p2p(&self) -> Result<&std::sync::Arc<crate::p2p::P2pNode>> {
        self.node.get().ok_or_else(|| anyhow!("P2P-узел не запущен"))
    }

    /// Небольшой файл целиком (latest.json, манифест, новости) — с перебором зеркал.
    pub async fn get(&self, rel: &str, max_size: u64) -> Result<Vec<u8>> {
        let n = self.mirrors.len();
        let start = self.rr.fetch_add(1, Ordering::Relaxed);
        let mut last = anyhow!("нет зеркал");
        for i in 0..n * 2 {
            let m = &self.mirrors[(start + i) % n];
            match self.get_from(m, rel, max_size).await {
                Ok(b) => return Ok(b),
                Err(e) => last = e,
            }
        }
        Err(last)
    }

    async fn get_from(&self, m: &Mirror, rel: &str, max_size: u64) -> Result<Vec<u8>> {
        match m {
            Mirror::Http(base) => {
                let url = format!("{base}{rel}");
                let resp = self
                    .client
                    .get(&url)
                    .timeout(Duration::from_secs(60))
                    .send()
                    .await
                    .map_err(|e| anyhow!("{url}: {e}"))?;
                if !resp.status().is_success() {
                    bail!("{url}: HTTP {}", resp.status());
                }
                if resp.content_length().unwrap_or(0) > max_size {
                    bail!("{url}: файл слишком большой");
                }
                let b = resp.bytes().await?;
                if b.len() as u64 > max_size {
                    bail!("{url}: файл слишком большой");
                }
                Ok(b.to_vec())
            }
            Mirror::P2p(id) => self.p2p()?.get_file(*id, rel, max_size).await,
            Mirror::Local(p) => {
                let path = p.join(rel);
                let b = tokio::fs::read(&path).await.map_err(|e| anyhow!("{}: {e}", path.display()))?;
                if b.len() as u64 > max_size {
                    bail!("{}: файл слишком большой", path.display());
                }
                Ok(b)
            }
        }
    }

    /// Файл целиком кусками по 1 МБ: повтор и смена зеркала при обрыве, прогресс `(готово, всего)`.
    pub async fn download_chunked(&self, rel: &str, size: u64, progress: &(dyn Fn(u64, u64) + Sync)) -> Result<Vec<u8>> {
        const STEP: u64 = 1 << 20;
        let mut out = Vec::with_capacity(size as usize);
        let (mut fails, mut mirror) = (0u32, 0usize);
        while (out.len() as u64) < size {
            let start = out.len() as u64;
            let end = (start + STEP).min(size);
            let r: Result<()> = async {
                let mut s = tokio::time::timeout(std::time::Duration::from_secs(30), self.range(mirror, rel, start, end))
                    .await
                    .map_err(|_| anyhow!("сервер не отвечает"))??;
                let mut got = 0u64;
                while got < end - start {
                    let b = tokio::time::timeout(std::time::Duration::from_secs(30), s.next())
                        .await
                        .map_err(|_| anyhow!("нет данных 30 с"))?
                        .ok_or_else(|| anyhow!("сервер оборвал передачу"))??;
                    let take = (b.len() as u64).min(end - start - got) as usize;
                    out.extend_from_slice(&b[..take]);
                    got += take as u64;
                    progress(out.len() as u64, size);
                }
                Ok(())
            }
            .await;
            if let Err(e) = r {
                out.truncate(start as usize);
                fails += 1;
                mirror += 1;
                if fails > 10 {
                    return Err(e.context(format!("не удалось скачать {rel}")));
                }
                tokio::time::sleep(std::time::Duration::from_millis(500 * fails as u64)).await;
            }
        }
        Ok(out)
    }

    /// Поток байт диапазона [start, end) файла `rel` с зеркала `mirror`.
    pub async fn range(&self, mirror: usize, rel: &str, start: u64, end: u64) -> Result<ByteStream> {
        match &self.mirrors[mirror % self.mirrors.len()] {
            Mirror::P2p(id) => self.p2p()?.range(*id, rel, start, end).await,
            Mirror::Http(base) => {
                let url = format!("{base}{rel}");
                let resp = self
                    .client
                    .get(&url)
                    .header(reqwest::header::RANGE, format!("bytes={}-{}", start, end - 1))
                    .send()
                    .await
                    .map_err(|e| anyhow!("{url}: {e}"))?;
                let st = resp.status().as_u16();
                // 200 допустим только для диапазона с нуля: лишний хвост просто не дочитываем.
                if st != 206 && !(st == 200 && start == 0) {
                    bail!("{url}: HTTP {st} (сервер должен поддерживать Range)");
                }
                Ok(resp.bytes_stream().map(|r| r.map_err(anyhow::Error::from)).boxed())
            }
            Mirror::Local(p) => {
                let path = p.join(rel);
                let mut f = tokio::fs::File::open(&path)
                    .await
                    .map_err(|e| anyhow!("{}: {e}", path.display()))?;
                f.seek(SeekFrom::Start(start)).await?;
                let s = stream::unfold((f, end - start), |(mut f, left)| async move {
                    if left == 0 {
                        return None;
                    }
                    let n = left.min(1 << 20) as usize;
                    let mut buf = vec![0u8; n];
                    match f.read_exact(&mut buf).await {
                        Ok(_) => Some((Ok(Bytes::from(buf)), (f, left - n as u64))),
                        Err(e) => Some((Err(anyhow::Error::from(e)), (f, 0))),
                    }
                });
                Ok(s.boxed())
            }
        }
    }
}
