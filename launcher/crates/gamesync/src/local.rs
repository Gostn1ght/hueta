//! Локальное состояние установки в `<игра>/.launcher/state`.

use crate::manifest::{Hash, Manifest};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

pub const STATE_DIR: &str = ".launcher";
pub const PART_EXT: &str = ".nwpart";

#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub struct IndexEntry {
    pub size: u64,
    pub mtime: u64,
    pub hash: Hash,
}

/// Проверенные файлы: путь → (размер, mtime, хеш). Совпадение size+mtime = файл не трогали.
#[derive(Serialize, Deserialize, Default, Clone)]
pub struct Index {
    pub files: HashMap<String, IndexEntry>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub struct Installed {
    pub version: String,
    pub manifest_hash: String,
    pub updated: u64,
}

pub fn mtime_of(meta: &fs::Metadata) -> u64 {
    meta.modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0)
}

pub fn now_unix() -> u64 {
    std::time::SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

pub fn part_path(p: &Path) -> PathBuf {
    let mut s = p.as_os_str().to_owned();
    s.push(PART_EXT);
    PathBuf::from(s)
}

pub struct Local {
    pub dir: PathBuf,
}

fn write_atomic(path: &Path, data: &[u8]) -> Result<()> {
    if let Some(p) = path.parent() {
        fs::create_dir_all(p)?;
    }
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, data)?;
    fs::rename(&tmp, path)?;
    Ok(())
}

impl Local {
    pub fn new(dir: &Path) -> Self {
        Self { dir: dir.to_path_buf() }
    }

    pub fn state_dir(&self) -> PathBuf {
        self.dir.join(STATE_DIR).join("state")
    }

    pub fn load_manifest(&self) -> Option<Manifest> {
        let b = fs::read(self.state_dir().join("manifest.bin")).ok()?;
        Manifest::decode(&b).ok()
    }

    pub fn save_manifest(&self, bytes: &[u8]) -> Result<()> {
        write_atomic(&self.state_dir().join("manifest.bin"), bytes)
    }

    pub fn load_index(&self) -> Index {
        fs::read(self.state_dir().join("index.bin"))
            .ok()
            .and_then(|b| bincode::deserialize(&b).ok())
            .unwrap_or_default()
    }

    pub fn save_index(&self, idx: &Index) -> Result<()> {
        write_atomic(&self.state_dir().join("index.bin"), &bincode::serialize(idx)?)
    }

    pub fn installed(&self) -> Option<Installed> {
        let b = fs::read(self.state_dir().join("installed.json")).ok()?;
        serde_json::from_slice(&b).ok()
    }

    pub fn save_installed(&self, i: &Installed) -> Result<()> {
        write_atomic(&self.state_dir().join("installed.json"), &serde_json::to_vec_pretty(i)?)
    }
}

#[derive(Serialize, Clone, Debug, Default)]
pub struct QuickCheck {
    pub total: usize,
    pub ok: usize,
    pub bad: Vec<String>,
}

pub fn glob_set(patterns: &[String]) -> Result<globset::GlobSet> {
    let mut b = globset::GlobSetBuilder::new();
    for p in patterns {
        b.add(globset::GlobBuilder::new(p).case_insensitive(true).build()?);
    }
    Ok(b.build()?)
}

/// Быстрая проверка без чтения содержимого: наличие, размер, mtime.
/// `user_files` — файлы игрока: достаточно, чтобы они существовали.
pub fn quick_check(dir: &Path, user_files: &[String]) -> Option<QuickCheck> {
    let local = Local::new(dir);
    let m = local.load_manifest()?;
    let idx = local.load_index();
    let user = glob_set(user_files).unwrap_or_else(|_| globset::GlobSet::empty());
    let mut q = QuickCheck { total: m.files.len(), ..Default::default() };
    for f in &m.files {
        if user.is_match(&f.path) && dir.join(&f.path).is_file() {
            q.ok += 1;
            continue;
        }
        let good = match (fs::metadata(dir.join(&f.path)), idx.files.get(&f.path)) {
            (Ok(meta), Some(e)) => meta.len() == f.size && e.size == f.size && e.hash == f.hash && e.mtime == mtime_of(&meta),
            _ => false,
        };
        if good {
            q.ok += 1;
        } else if q.bad.len() < 200 {
            q.bad.push(f.path.clone());
        }
    }
    Some(q)
}
