//! Упаковка папки игры в релиз: чанки (FastCDC + BLAKE3) → pack-файлы (zstd) → подписанный
//! манифест. Используется и консольным `packer`, и веб-панелью сервера.

use anyhow::{Context, Result};
use fastcdc::v2020::{FastCDC, StreamCDC};
use gamesync::manifest::{file_hash, Chunk, FileEntry, Hash, LauncherRelease, Manifest, Release, FORMAT};
use parking_lot::Mutex;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering::Relaxed};
use std::time::{Duration, Instant};

pub const MIN_CHUNK: u32 = 256 << 10;
pub const AVG_CHUNK: u32 = 1 << 20;
pub const MAX_CHUNK: u32 = 4 << 20;

#[derive(Serialize, Deserialize, Clone)]
pub struct StoreEntry {
    pub pack: String,
    pub offset: u64,
    pub csize: u32,
    pub size: u32,
    pub zstd: bool,
}

/// Все чанки, когда-либо выложенные в эту папку publish — для дедупликации между версиями,
/// и кеш нарезки файлов: неизменённый файл (размер + mtime) не перечитывается.
#[derive(Serialize, Deserialize, Default)]
pub struct Store {
    pub chunks: HashMap<Hash, StoreEntry>,
    pub files: HashMap<String, CachedFile>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct CachedFile {
    pub size: u64,
    pub mtime: u64,
    pub chunks: Vec<(Hash, u32)>,
}

pub fn load_store(out: &Path) -> Store {
    fs::read(out.join("chunkstore.bin")).ok().and_then(|b| bincode::deserialize(&b).ok()).unwrap_or_default()
}

pub fn read_release(out: &Path) -> Option<Release> {
    let b = fs::read(out.join("latest.json")).ok()?;
    let s: gamesync::manifest::SignedRelease = serde_json::from_slice(&b).ok()?;
    serde_json::from_str(&s.payload).ok()
}

pub struct PackOptions {
    pub input: PathBuf,
    pub out: PathBuf,
    pub version: String,
    pub secret_key: String,
    pub product: String,
    pub level: i32,
    pub pack_size: u64,
    pub exclude: Vec<String>,
    pub launcher: Option<PathBuf>,
    pub launcher_version: Option<String>,
    pub rescan: bool,
}

#[derive(Serialize, Clone, Debug, Default)]
pub struct PackProgress {
    pub files: usize,
    pub total: u64,
    pub done: u64,
    pub new_bytes: u64,
    pub speed: f64,
}

#[derive(Serialize, Clone, Debug, Default)]
pub struct PackReport {
    pub version: String,
    pub manifest: String,
    pub manifest_size: u64,
    pub files: usize,
    pub game_size: u64,
    pub chunks: usize,
    pub server_bytes: u64,
    pub new_bytes: u64,
    pub seconds: f64,
}

pub fn compress(d: &[u8], level: i32) -> (Vec<u8>, bool) {
    // Быстрая проба: уже сжатые/зашифрованные данные не мучаем высоким уровнем.
    if d.len() > 128 << 10 {
        let probe = &d[..64 << 10];
        if let Ok(p) = zstd::bulk::compress(probe, 1) {
            if p.len() as f64 > probe.len() as f64 * 0.97 {
                return (d.to_vec(), false);
            }
        }
    }
    match zstd::bulk::compress(d, level) {
        Ok(c) if (c.len() as f64) < d.len() as f64 * 0.98 => (c, true),
        _ => (d.to_vec(), false),
    }
}

pub fn sanitize(s: &str) -> String {
    s.chars().map(|c| if c.is_ascii_alphanumeric() || c == '.' || c == '-' || c == '_' { c } else { '_' }).collect()
}

pub fn pack(o: &PackOptions, progress: &(dyn Fn(&PackProgress) + Sync)) -> Result<PackReport> {
    let t0 = Instant::now();
    let (input, out, version) = (o.input.as_path(), o.out.as_path(), o.version.as_str());
    gamesync::sign::public_from_secret(&o.secret_key)?;
    if !input.is_dir() {
        anyhow::bail!("папка игры не найдена: {}", input.display());
    }
    fs::create_dir_all(out.join("packs"))?;
    fs::create_dir_all(out.join("manifests"))?;

    let mut gb = globset::GlobSetBuilder::new();
    for p in [".launcher/**", "**/*.nwpart"].iter().map(|s| s.to_string()).chain(o.exclude.iter().cloned()) {
        gb.add(globset::GlobBuilder::new(&p).case_insensitive(true).build()?);
    }
    let excl = gb.build()?;

    let mut files = Vec::new();
    for e in walkdir::WalkDir::new(input).follow_links(false) {
        let e = e?;
        if !e.file_type().is_file() {
            continue;
        }
        let rel = e.path().strip_prefix(input)?.to_string_lossy().replace('\\', "/");
        if excl.is_match(&rel) || gamesync::policy::is_never_distributed(&rel) {
            continue;
        }
        let meta = e.metadata()?;
        files.push((rel, e.path().to_path_buf(), meta.len(), gamesync::local::mtime_of(&meta)));
    }
    files.sort_by(|a, b| a.0.cmp(&b.0));
    let total: u64 = files.iter().map(|f| f.2).sum();

    let store = load_store(out);
    let claimed: Mutex<HashSet<Hash>> = Mutex::new(store.chunks.keys().copied().collect());

    let run = format!("{:x}", gamesync::local::now_unix());
    let (tx, rx) = std::sync::mpsc::sync_channel::<(Hash, u32, Vec<u8>, bool)>(64);
    let out_w = out.to_path_buf();
    let pack_size = o.pack_size;
    let writer = std::thread::spawn(move || -> Result<HashMap<Hash, StoreEntry>> {
        let mut new = HashMap::new();
        let mut cur: Option<(String, BufWriter<File>, u64)> = None;
        let mut n = 0;
        for (h, size, data, z) in rx {
            if cur.as_ref().map_or(true, |c| c.2 >= pack_size) {
                if let Some((_, mut w, _)) = cur.take() {
                    w.flush()?;
                }
                let name = format!("packs/{run}-{n:04}.pack");
                n += 1;
                let f = File::create(out_w.join(&name))?;
                cur = Some((name, BufWriter::with_capacity(8 << 20, f), 0));
            }
            let c = cur.as_mut().unwrap();
            c.1.write_all(&data)?;
            new.insert(h, StoreEntry { pack: c.0.clone(), offset: c.2, csize: data.len() as u32, size, zstd: z });
            c.2 += data.len() as u64;
        }
        if let Some((_, mut w, _)) = cur.take() {
            w.flush()?;
        }
        Ok(new)
    });

    let done = AtomicU64::new(0);
    let new_bytes = AtomicU64::new(0);
    let stop = AtomicBool::new(false);
    let level = o.level;
    let nfiles = files.len();
    let results: Vec<(String, u64, Vec<(Hash, u32)>)> = std::thread::scope(|s| {
        s.spawn(|| {
            let t = Instant::now();
            loop {
                let fin = stop.load(Relaxed);
                let d = done.load(Relaxed);
                progress(&PackProgress {
                    files: nfiles,
                    total,
                    done: d,
                    new_bytes: new_bytes.load(Relaxed),
                    speed: d as f64 / t.elapsed().as_secs_f64().max(0.001),
                });
                if fin {
                    break;
                }
                std::thread::sleep(Duration::from_millis(500));
            }
        });
        let r = files
            .par_iter()
            .map(|(rel, abs, fsize, mtime)| -> Result<(String, u64, Vec<(Hash, u32)>)> {
                if !o.rescan {
                    if let Some(c) = store.files.get(rel) {
                        if c.size == *fsize && c.mtime == *mtime && c.chunks.iter().all(|(h, _)| store.chunks.contains_key(h)) {
                            done.fetch_add(*fsize, Relaxed);
                            return Ok((rel.clone(), *fsize, c.chunks.clone()));
                        }
                    }
                }
                let f = File::open(abs).with_context(|| format!("чтение {}", abs.display()))?;
                let size = f.metadata()?.len();
                let mut list = Vec::new();
                let mut batch: Vec<(Hash, Vec<u8>)> = Vec::new();
                let mut batch_bytes = 0usize;
                let flush = |batch: &mut Vec<(Hash, Vec<u8>)>| -> Result<()> {
                    let out: Vec<_> = std::mem::take(batch)
                        .into_par_iter()
                        .map(|(h, d)| {
                            let (c, z) = compress(&d, level);
                            (h, d.len() as u32, c, z)
                        })
                        .collect();
                    for o in out {
                        new_bytes.fetch_add(o.2.len() as u64, Relaxed);
                        tx.send(o).map_err(|_| anyhow::anyhow!("запись pack-файлов прервалась"))?;
                    }
                    Ok(())
                };
                let mut on_chunk = |data: Vec<u8>| -> Result<()> {
                    let h = *blake3::hash(&data).as_bytes();
                    list.push((h, data.len() as u32));
                    done.fetch_add(data.len() as u64, Relaxed);
                    if claimed.lock().insert(h) {
                        batch_bytes += data.len();
                        batch.push((h, data));
                        if batch_bytes >= 32 << 20 {
                            flush(&mut batch)?;
                            batch_bytes = 0;
                        }
                    }
                    Ok(())
                };
                if size <= 64 << 20 {
                    // Мелкие файлы целиком в память: StreamCDC выделяет буфер max_size на каждый файл.
                    let mut d = Vec::with_capacity(size as usize);
                    BufReader::new(f).read_to_end(&mut d).with_context(|| format!("чтение {}", abs.display()))?;
                    for c in FastCDC::new(&d, MIN_CHUNK, AVG_CHUNK, MAX_CHUNK) {
                        on_chunk(d[c.offset..c.offset + c.length].to_vec())?;
                    }
                } else {
                    for c in StreamCDC::new(f, MIN_CHUNK, AVG_CHUNK, MAX_CHUNK) {
                        on_chunk(c.with_context(|| format!("чтение {}", abs.display()))?.data)?;
                    }
                }
                flush(&mut batch)?;
                Ok((rel.clone(), size, list))
            })
            .collect::<Result<Vec<_>>>();
        stop.store(true, Relaxed);
        r
    })?;
    drop(tx);
    let new = writer.join().map_err(|_| anyhow::anyhow!("запись pack-файлов упала"))??;

    let mut store = store;
    store.chunks.extend(new);
    store.files = files
        .iter()
        .zip(results.iter())
        .map(|((rel, _, _, mtime), (_, size, list))| (rel.clone(), CachedFile { size: *size, mtime: *mtime, chunks: list.clone() }))
        .collect();

    let mut m = Manifest { format: FORMAT, version: version.to_string(), created: gamesync::local::now_unix(), ..Default::default() };
    let mut ids: HashMap<Hash, u32> = HashMap::new();
    let mut pack_ids: HashMap<String, u32> = HashMap::new();
    for (rel, size, list) in &results {
        let mut cids = Vec::with_capacity(list.len());
        for (h, _) in list {
            let id = match ids.get(h) {
                Some(&id) => id,
                None => {
                    let e = store.chunks.get(h).context("чанк пропал из хранилища")?;
                    let pid = *pack_ids.entry(e.pack.clone()).or_insert_with(|| {
                        m.packs.push(e.pack.clone());
                        (m.packs.len() - 1) as u32
                    });
                    m.chunks.push(Chunk { hash: *h, pack: pid, offset: e.offset, csize: e.csize, size: e.size, zstd: e.zstd });
                    let id = (m.chunks.len() - 1) as u32;
                    ids.insert(*h, id);
                    id
                }
            };
            cids.push(id);
        }
        m.files.push(FileEntry { path: rel.clone(), size: *size, hash: file_hash(list.iter().copied()), chunks: cids });
    }
    m.validate()?;
    let mbytes = m.encode()?;
    let mhash = hex::encode(blake3::hash(&mbytes).as_bytes());
    let mname = format!("manifests/{}-{}.bin", sanitize(version), &mhash[..8]);
    fs::write(out.join(&mname), &mbytes)?;

    let launcher = match &o.launcher {
        Some(p) => {
            let b = fs::read(p).with_context(|| format!("чтение {}", p.display()))?;
            let lv = o.launcher_version.clone().context("укажите версию лаунчера")?;
            let name = format!("launcher/{}Launcher-{}.exe", sanitize(&o.product), sanitize(&lv));
            fs::create_dir_all(out.join("launcher"))?;
            fs::write(out.join(&name), &b)?;
            Some(LauncherRelease { version: lv, path: name, hash: hex::encode(blake3::hash(&b).as_bytes()), size: b.len() as u64 })
        }
        None => read_release(out).and_then(|r| r.launcher),
    };

    let rel = Release {
        product: o.product.clone(),
        version: version.to_string(),
        manifest: mname.clone(),
        manifest_hash: mhash,
        manifest_size: mbytes.len() as u64,
        game_size: total,
        files: m.files.len() as u64,
        published: gamesync::local::now_unix(),
        launcher,
    };
    fs::write(out.join("chunkstore.bin"), bincode::serialize(&store)?)?;
    let signed = gamesync::sign::sign_release(&rel, &o.secret_key)?;
    let tmp = out.join("latest.json.tmp");
    fs::write(&tmp, signed)?;
    fs::rename(&tmp, out.join("latest.json"))?;
    if !out.join("news.json").exists() {
        fs::write(out.join("news.json"), include_str!("news_example.json"))?;
    }

    Ok(PackReport {
        version: version.to_string(),
        manifest: mname,
        manifest_size: mbytes.len() as u64,
        files: m.files.len(),
        game_size: total,
        chunks: m.chunks.len(),
        server_bytes: m.chunks.iter().map(|c| c.csize as u64).sum(),
        new_bytes: new_bytes.load(Relaxed),
        seconds: t0.elapsed().as_secs_f64(),
    })
}

/// Выложить новый лаунчер, не трогая игру: exe кладётся в `launcher/`, `latest.json`
/// переподписывается. Лаунчеры игроков обновятся при следующем запуске, установщик
/// будет ставить этот exe.
/// Номер версии, зашитый в exe лаунчера (метка LZLAUNCHER_VERSION=…;).
pub fn launcher_version_of(exe_bytes: &[u8]) -> Option<String> {
    let mark = b"LZLAUNCHER_VERSION=";
    let pos = exe_bytes.windows(mark.len()).position(|w| w == mark)? + mark.len();
    let end = exe_bytes[pos..].iter().take(32).position(|&c| c == b';')? + pos;
    let v = std::str::from_utf8(&exe_bytes[pos..end]).ok()?;
    v.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-').then(|| v.to_string())
}

pub fn publish_launcher(out: &Path, exe: &Path, version: &str, secret_key: &str) -> Result<LauncherRelease> {
    let mut rel = read_release(out).context("сначала опубликуйте игру: лаунчер прикрепляется к релизу")?;
    let b = fs::read(exe).with_context(|| format!("чтение {}", exe.display()))?;
    if b.len() < 1024 || &b[..2] != b"MZ" {
        anyhow::bail!("{} — не exe-файл", exe.display());
    }
    let embedded = launcher_version_of(&b);
    let version = match (version.trim(), embedded.as_deref()) {
        ("", Some(v)) => v.to_string(),
        ("", None) => anyhow::bail!("в exe нет метки версии — укажите версию вручную"),
        (v, Some(e)) if v != e => anyhow::bail!("в exe зашита версия {e}, а указана {v} — оставьте поле пустым"),
        (v, _) => v.to_string(),
    };
    let version = version.as_str();
    let hash = hex::encode(blake3::hash(&b).as_bytes());
    let name = format!("launcher/{}Launcher-{}-{}.exe", sanitize(&rel.product), sanitize(version), &hash[..8]);
    fs::create_dir_all(out.join("launcher"))?;
    fs::write(out.join(&name), &b)?;
    let l = LauncherRelease { version: version.to_string(), path: name, hash, size: b.len() as u64 };
    rel.launcher = Some(l.clone());
    rel.published = gamesync::local::now_unix();
    let signed = gamesync::sign::sign_release(&rel, secret_key)?;
    let tmp = out.join("latest.json.tmp");
    fs::write(&tmp, signed)?;
    fs::rename(&tmp, out.join("latest.json"))?;
    Ok(l)
}

pub fn keygen(out: &Path) -> Result<String> {
    fs::create_dir_all(out)?;
    let sk_path = out.join("secret.key");
    if sk_path.exists() {
        anyhow::bail!("{} уже существует — не перезаписываю (иначе старые лаунчеры перестанут доверять серверу)", sk_path.display());
    }
    let mut seed = [0u8; 32];
    getrandom::getrandom(&mut seed).map_err(|e| anyhow::anyhow!("getrandom: {e}"))?;
    let sk = hex::encode(seed);
    let pk = gamesync::sign::public_from_secret(&sk)?;
    fs::write(&sk_path, &sk)?;
    fs::write(out.join("public.key"), &pk)?;
    Ok(pk)
}
