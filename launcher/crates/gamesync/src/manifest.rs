//! Формат манифеста: список файлов, каждый — последовательность чанков.
//! Чанки уникальны по BLAKE3-хешу и лежат в pack-файлах на сервере.

use anyhow::{anyhow, bail, Context, Result};
use bincode::Options;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

pub type Hash = [u8; 32];
pub const FORMAT: u32 = 1;
const MAX_MANIFEST_RAW: u64 = 1 << 30;

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Chunk {
    pub hash: Hash,
    /// Индекс в `Manifest::packs`.
    pub pack: u32,
    /// Смещение сжатых данных внутри pack-файла.
    pub offset: u64,
    /// Размер на сервере (после сжатия).
    pub csize: u32,
    /// Размер исходных данных.
    pub size: u32,
    pub zstd: bool,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct FileEntry {
    /// Относительный путь с разделителем `/`.
    pub path: String,
    pub size: u64,
    /// `file_hash` от списка чанков — идентичность содержимого файла.
    pub hash: Hash,
    pub chunks: Vec<u32>,
}

#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct Manifest {
    pub format: u32,
    pub version: String,
    pub created: u64,
    pub packs: Vec<String>,
    pub chunks: Vec<Chunk>,
    pub files: Vec<FileEntry>,
}

fn codec() -> impl bincode::Options {
    bincode::options().with_limit(MAX_MANIFEST_RAW)
}

impl Manifest {
    pub fn encode(&self) -> Result<Vec<u8>> {
        let raw = codec().serialize(self)?;
        Ok(zstd::encode_all(&raw[..], 19)?)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self> {
        let raw = zstd::decode_all(bytes).context("манифест повреждён (zstd)")?;
        let m: Manifest = codec().deserialize(&raw).context("манифест повреждён")?;
        if m.format != FORMAT {
            bail!("неподдерживаемый формат манифеста {}", m.format);
        }
        m.validate()?;
        Ok(m)
    }

    pub fn validate(&self) -> Result<()> {
        for p in &self.packs {
            if !safe_rel_path(p) {
                bail!("недопустимое имя pack-файла: {p}");
            }
        }
        for c in &self.chunks {
            if c.pack as usize >= self.packs.len() {
                bail!("чанк ссылается на несуществующий pack");
            }
        }
        let mut seen = HashSet::new();
        for f in &self.files {
            if !safe_rel_path(&f.path) {
                bail!("недопустимый путь в манифесте: {}", f.path);
            }
            if !seen.insert(f.path.to_lowercase()) {
                bail!("путь повторяется: {}", f.path);
            }
            let mut sum = 0u64;
            for &ci in &f.chunks {
                let c = self
                    .chunks
                    .get(ci as usize)
                    .ok_or_else(|| anyhow!("неверный индекс чанка в {}", f.path))?;
                sum += c.size as u64;
            }
            if sum != f.size {
                bail!("размер не сходится с чанками: {}", f.path);
            }
        }
        Ok(())
    }

    pub fn total_size(&self) -> u64 {
        self.files.iter().map(|f| f.size).sum()
    }

    /// Чанки файла с их смещениями внутри файла.
    pub fn spans<'a>(&'a self, f: &'a FileEntry) -> impl Iterator<Item = Span> + 'a {
        let mut off = 0u64;
        f.chunks.iter().map(move |&ci| {
            let c = &self.chunks[ci as usize];
            let s = Span { chunk: ci, offset: off, size: c.size, hash: c.hash };
            off += c.size as u64;
            s
        })
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Span {
    pub chunk: u32,
    pub offset: u64,
    pub size: u32,
    pub hash: Hash,
}

pub fn safe_rel_path(p: &str) -> bool {
    !p.is_empty()
        && !p.starts_with('/')
        && !p.contains('\\')
        && !p.contains(':')
        && p.split('/').all(|s| !s.is_empty() && s != "." && s != "..")
}

pub fn file_hash(chunks: impl Iterator<Item = (Hash, u32)>) -> Hash {
    let mut h = blake3::Hasher::new();
    for (c, s) in chunks {
        h.update(&c);
        h.update(&s.to_le_bytes());
    }
    *h.finalize().as_bytes()
}

pub fn hex32(s: &str) -> Result<Hash> {
    let v = hex::decode(s.trim()).context("неверный hex")?;
    v.try_into().map_err(|_| anyhow!("ожидалось 32 байта"))
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct LauncherRelease {
    pub version: String,
    pub path: String,
    pub hash: String,
    pub size: u64,
}

/// Содержимое `latest.json` (подписывается ed25519).
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Release {
    pub product: String,
    pub version: String,
    pub manifest: String,
    pub manifest_hash: String,
    pub manifest_size: u64,
    pub game_size: u64,
    pub files: u64,
    pub published: u64,
    pub launcher: Option<LauncherRelease>,
}

#[derive(Serialize, Deserialize)]
pub struct SignedRelease {
    pub payload: String,
    pub signature: String,
}
