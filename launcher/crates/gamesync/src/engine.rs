//! Синхронизация установки с манифестом.
//!
//! 1. План: доверенные файлы (size+mtime из индекса) пропускаются, остальные хешируются
//!    по границам чанков. Совпавшие куски — уже на месте или служат локальным источником.
//! 2. Копирование: нужные чанки, которые уже есть на диске (в старой версии файла,
//!    в соседнем файле, в недокачанном .nwpart), копируются локально.
//! 3. Загрузка: остальные чанки — Range-запросами по pack-файлам, N соединений,
//!    соседние чанки склеиваются в один запрос. Распаковка и проверка BLAKE3 на лету,
//!    запись сразу по месту. Повреждённые чанки перекачиваются с другого зеркала.
//! 4. Удаление: только файлы прошлой версии, которых нет в новой. Чужое не трогаем.

use crate::local::{mtime_of, now_unix, part_path, Index, IndexEntry, Installed, Local};
use crate::manifest::{Hash, Manifest, Release, Span};
use crate::source::Sources;
use crate::util::{free_space, human_bytes, pread, pwrite, rename_retry};
use anyhow::{anyhow, bail, Context, Result};
use bytes::BytesMut;
use futures_util::StreamExt;
use parking_lot::{Mutex, RwLock};
use rayon::prelude::*;
use serde::Serialize;
use std::borrow::Cow;
use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::{self, File, OpenOptions};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, AtomicUsize, Ordering::*};
use std::sync::Arc;
use std::time::{Duration, Instant};

pub const CANCELLED: &str = "Отменено";

pub fn is_cancelled(e: &anyhow::Error) -> bool {
    e.chain().any(|c| c.to_string() == CANCELLED)
}

#[derive(Clone, Debug)]
pub struct Options {
    pub connections: usize,
    pub max_retries: u32,
    pub range_max: u64,
    pub gap: u64,
    pub stall_timeout: Duration,
    /// Глоб-шаблоны путей, которые никогда не удаляются.
    pub keep: Vec<String>,
    /// Папки, очищаемые при смене версии (кеш шейдеров и т.п.).
    pub clean_on_update: Vec<String>,
    /// Файлы игрока (настройки, которые меняет игра): ставятся, если их нет, но никогда не
    /// перезаписываются, не «чинятся» и не удаляются.
    pub user_files: Vec<String>,
    pub verify_threads: usize,
    /// Качать и у других игроков (P2P), если сервер-трекер их знает.
    pub use_peers: bool,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            connections: 16,
            max_retries: 6,
            range_max: 32 << 20,
            gap: 512 << 10,
            stall_timeout: Duration::from_secs(30),
            keep: vec![],
            clean_on_update: vec![],
            user_files: vec![],
            verify_threads: 0,
            use_peers: true,
        }
    }
}

#[derive(Serialize, Clone, Debug, Default)]
pub struct Progress {
    pub phase: String,
    pub text: String,
    pub done: u64,
    pub total: u64,
    pub net_done: u64,
    pub net_total: u64,
    /// Сколько из скачанного пришло от других игроков (P2P).
    pub net_peers: u64,
    pub peers: u32,
    pub speed: f64,
    pub eta: Option<u64>,
    pub files_done: u64,
    pub files_total: u64,
}

pub trait Reporter: Send + Sync {
    fn progress(&self, p: &Progress);
    fn log(&self, line: &str);
}

#[derive(Serialize, Clone, Debug, Default)]
pub struct Summary {
    pub version: String,
    pub downloaded: u64,
    pub network: u64,
    pub from_peers: u64,
    pub copied: u64,
    pub written_files: usize,
    pub verified_ok: usize,
    pub deleted: usize,
    pub seconds: f64,
}

#[derive(Default)]
struct Ctr {
    done: AtomicU64,
    total: AtomicU64,
    net: AtomicU64,
    net_total: AtomicU64,
    net_peers: AtomicU64,
    files_done: AtomicU64,
    files_total: AtomicU64,
    peers: AtomicU32,
    phase: Mutex<(String, String)>,
}

impl Ctr {
    fn phase(&self, id: &str, text: &str, total: u64, files: u64) {
        *self.phase.lock() = (id.into(), text.into());
        self.done.store(0, Relaxed);
        self.total.store(total, Relaxed);
        self.files_done.store(0, Relaxed);
        self.files_total.store(files, Relaxed);
    }
}

#[derive(Clone, Copy, Debug)]
struct Target {
    work: usize,
    offset: u64,
}

struct WorkFile {
    file: usize,
    in_place: bool,
    remaining: AtomicUsize,
}

struct Plan {
    work: Vec<WorkFile>,
    copies: Vec<(PathBuf, Vec<(u64, u32, Vec<Target>)>)>,
    downloads: HashMap<u32, Vec<Target>>,
    ready: Vec<usize>,
    verified_ok: usize,
    index: Index,
    delete: Vec<String>,
    new_part_bytes: u64,
}

pub struct Engine {
    pub dir: PathBuf,
    pub sources: Arc<Sources>,
    pub opts: Options,
    pub cancel: Arc<AtomicBool>,
    pub rep: Arc<dyn Reporter>,
}

pub async fn fetch_release(sources: &Sources, public_key: &str) -> Result<Release> {
    let b = sources.get("latest.json", 1 << 20).await.context("не удалось получить latest.json")?;
    crate::sign::verify_release(&b, public_key)
}

pub async fn fetch_manifest(sources: &Sources, r: &Release) -> Result<(Arc<Manifest>, Vec<u8>)> {
    let b = sources.get(&r.manifest, r.manifest_size.max(1) + 16).await.context("не удалось скачать манифест")?;
    if hex::encode(blake3::hash(&b).as_bytes()) != r.manifest_hash {
        bail!("хеш манифеста не совпал с подписанным релизом");
    }
    let m = tokio::task::spawn_blocking({
        let b = b.clone();
        move || Manifest::decode(&b)
    })
    .await??;
    Ok((Arc::new(m), b))
}

fn hash_spans(path: &Path, spans: &[Span], ctr: &Ctr, cancel: &AtomicBool) -> Result<Vec<bool>> {
    let mut out = vec![false; spans.len()];
    let mut f = match File::open(path) {
        Ok(f) => f,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(out),
        Err(e) => return Err(anyhow!("не удаётся открыть {}: {e} (игра запущена?)", path.display())),
    };
    let len = f.metadata()?.len();
    let mut buf = vec![0u8; spans.iter().map(|s| s.size as usize).max().unwrap_or(0)];
    for (k, s) in spans.iter().enumerate() {
        if cancel.load(Relaxed) {
            bail!(CANCELLED);
        }
        if s.offset + s.size as u64 > len {
            break;
        }
        let b = &mut buf[..s.size as usize];
        if f.read_exact(b).is_err() {
            break;
        }
        out[k] = blake3::hash(b).as_bytes() == &s.hash;
        ctr.done.fetch_add(s.size as u64, Relaxed);
    }
    Ok(out)
}

#[allow(clippy::too_many_arguments)]
fn plan(
    dir: &Path,
    m: &Manifest,
    old: Option<&Manifest>,
    mut index: Index,
    verify_all: bool,
    keep: &globset::GlobSet,
    user: &globset::GlobSet,
    ctr: &Ctr,
    cancel: &AtomicBool,
    pool: &rayon::ThreadPool,
) -> Result<Plan> {
    let n = m.files.len();
    let mut good = vec![false; n];
    let mut check = Vec::new();
    for (i, f) in m.files.iter().enumerate() {
        let p = dir.join(&f.path);
        let meta = fs::metadata(&p).ok().filter(|x| x.is_file());
        if let (true, Some(meta)) = (user.is_match(&f.path), &meta) {
            // Файл игрока уже есть — его содержимое не наше дело.
            index.files.insert(f.path.clone(), IndexEntry { size: meta.len(), mtime: mtime_of(meta), hash: f.hash });
            good[i] = true;
            continue;
        }
        if !verify_all {
            if let (Some(meta), Some(e)) = (&meta, index.files.get(&f.path)) {
                if meta.len() == f.size && e.size == f.size && e.hash == f.hash && e.mtime == mtime_of(meta) {
                    good[i] = true;
                    continue;
                }
            }
        }
        if f.size == 0 {
            if let Some(par) = p.parent() {
                fs::create_dir_all(par)?;
            }
            if meta.map(|x| x.len()) != Some(0) {
                File::create(&p).with_context(|| format!("создание {}", p.display()))?;
            }
            let meta = fs::metadata(&p)?;
            index.files.insert(f.path.clone(), IndexEntry { size: 0, mtime: mtime_of(&meta), hash: f.hash });
            good[i] = true;
            continue;
        }
        check.push(i);
    }

    // Хешируем то, чему не доверяем: сам файл и недокачанный .nwpart.
    let total: u64 = check
        .iter()
        .map(|&i| {
            let f = &m.files[i];
            let p = dir.join(&f.path);
            let a = fs::metadata(&p).map(|x| x.len().min(f.size)).unwrap_or(0);
            let b = fs::metadata(part_path(&p)).map(|x| if x.len() == f.size { f.size } else { 0 }).unwrap_or(0);
            a + b
        })
        .sum();
    if total > 0 {
        ctr.phase("verify", "Проверка файлов", total, check.len() as u64);
    } else {
        ctr.phase("prepare", "Подготовка", 0, 0);
    }

    struct Chk {
        i: usize,
        p_len: Option<u64>,
        p_good: Vec<bool>,
        part_good: Option<Vec<bool>>,
    }
    let results: Vec<Chk> = pool.install(|| {
        check
            .par_iter()
            .map(|&i| -> Result<Chk> {
                let f = &m.files[i];
                let p = dir.join(&f.path);
                let spans: Vec<Span> = m.spans(f).collect();
                let p_len = fs::metadata(&p).ok().filter(|x| x.is_file()).map(|x| x.len());
                let p_good = if p_len.is_some() { hash_spans(&p, &spans, ctr, cancel)? } else { vec![false; spans.len()] };
                let whole = p_len == Some(f.size) && p_good.iter().all(|&g| g);
                let pp = part_path(&p);
                let part_good = match fs::metadata(&pp) {
                    Ok(x) if !whole && x.len() == f.size => Some(hash_spans(&pp, &spans, ctr, cancel)?),
                    _ => None,
                };
                ctr.files_done.fetch_add(1, Relaxed);
                Ok(Chk { i, p_len, p_good, part_good })
            })
            .collect::<Result<Vec<_>>>()
    })?;

    // Файлы прошлой версии, которым можно доверять как источнику чанков.
    let mut old_trusted: HashSet<&str> = HashSet::new();
    if let Some(old) = old {
        for of in &old.files {
            if let (Ok(meta), Some(e)) = (fs::metadata(dir.join(&of.path)), index.files.get(&of.path)) {
                if meta.len() == of.size && e.size == of.size && e.hash == of.hash && e.mtime == mtime_of(&meta) {
                    old_trusted.insert(of.path.as_str());
                }
            }
        }
    }

    let mut verified_ok = 0;
    let mut work = Vec::new();
    let mut ready = Vec::new();
    let mut needs: Vec<(usize, Vec<Span>)> = Vec::new();
    let mut p_sources: Vec<(Hash, PathBuf, u64)> = Vec::new();
    let mut new_part_bytes = 0u64;
    for c in results {
        let f = &m.files[c.i];
        let p = dir.join(&f.path);
        let spans: Vec<Span> = m.spans(f).collect();
        if c.p_len == Some(f.size) && c.p_good.iter().all(|&g| g) {
            good[c.i] = true;
            verified_ok += 1;
            let meta = fs::metadata(&p)?;
            index.files.insert(f.path.clone(), IndexEntry { size: f.size, mtime: mtime_of(&meta), hash: f.hash });
            let _ = fs::remove_file(part_path(&p));
            continue;
        }
        index.files.remove(&f.path);
        let p_ok = c.p_good.iter().filter(|&&g| g).count();
        let part_ok = c.part_good.as_ref().map(|v| v.iter().filter(|&&g| g).count()).unwrap_or(0);
        // Чиним прямо в файле, если размер совпадает и это не доверенная старая версия
        // (старая версия — источник чанков для других файлов, её трогать до конца нельзя).
        let in_place = c.p_len == Some(f.size) && !old_trusted.contains(f.path.as_str()) && p_ok >= part_ok;
        let done_mask = if in_place {
            let _ = fs::remove_file(part_path(&p));
            c.p_good.clone()
        } else {
            if c.part_good.is_none() {
                new_part_bytes += f.size;
            }
            c.part_good.clone().unwrap_or_else(|| vec![false; spans.len()])
        };
        for (k, s) in spans.iter().enumerate() {
            if c.p_good[k] {
                p_sources.push((s.hash, p.clone(), s.offset));
            }
        }
        let need: Vec<Span> = spans.iter().enumerate().filter(|(k, _)| !done_mask[*k]).map(|(_, s)| *s).collect();
        let wi = work.len();
        work.push(WorkFile { file: c.i, in_place, remaining: AtomicUsize::new(need.len()) });
        if need.is_empty() {
            ready.push(wi);
        }
        needs.push((wi, need));
    }

    let needed: HashSet<Hash> = needs.iter().flat_map(|(_, v)| v.iter().map(|s| s.hash)).collect();
    let mut sources: HashMap<Hash, (PathBuf, u64)> = HashMap::new();
    {
        let mut add = |h: Hash, p: &Path, off: u64| {
            if needed.contains(&h) {
                sources.entry(h).or_insert_with(|| (p.to_path_buf(), off));
            }
        };
        for (i, f) in m.files.iter().enumerate() {
            if good[i] {
                let p = dir.join(&f.path);
                for s in m.spans(f) {
                    add(s.hash, &p, s.offset);
                }
            }
        }
        for (h, p, off) in &p_sources {
            add(*h, p, *off);
        }
        if let Some(old) = old {
            for of in &old.files {
                if old_trusted.contains(of.path.as_str()) {
                    let p = dir.join(&of.path);
                    for s in old.spans(of) {
                        add(s.hash, &p, s.offset);
                    }
                }
            }
        }
    }

    let mut downloads: HashMap<u32, Vec<Target>> = HashMap::new();
    let mut copy_map: HashMap<u32, (PathBuf, u64, Vec<Target>)> = HashMap::new();
    for (wi, need) in needs {
        for s in need {
            let t = Target { work: wi, offset: s.offset };
            if let Some((sp, so)) = sources.get(&s.hash) {
                copy_map.entry(s.chunk).or_insert_with(|| (sp.clone(), *so, vec![])).2.push(t);
            } else {
                downloads.entry(s.chunk).or_default().push(t);
            }
        }
    }
    let mut by_src: HashMap<PathBuf, Vec<(u64, u32, Vec<Target>)>> = HashMap::new();
    for (ci, (sp, so, t)) in copy_map {
        by_src.entry(sp).or_default().push((so, ci, t));
    }
    let mut copies: Vec<_> = by_src.into_iter().collect();
    for (_, v) in copies.iter_mut() {
        v.sort_by_key(|x| x.0);
    }

    let mut delete = Vec::new();
    if let Some(old) = old {
        let new_paths: HashSet<String> = m.files.iter().map(|f| f.path.to_lowercase()).collect();
        for of in &old.files {
            if !new_paths.contains(&of.path.to_lowercase()) && !keep.is_match(&of.path) && !user.is_match(&of.path) {
                delete.push(of.path.clone());
            }
        }
    }

    Ok(Plan { work, copies, downloads, ready, verified_ok, index, delete, new_part_bytes })
}

struct Exec {
    dir: PathBuf,
    m: Arc<Manifest>,
    work: Vec<WorkFile>,
    handles: Mutex<HashMap<usize, Arc<File>>>,
    index: Mutex<Index>,
    defer: AtomicBool,
    deferred: Mutex<Vec<usize>>,
    downloads: RwLock<HashMap<u32, Vec<Target>>>,
    ctr: Arc<Ctr>,
    rep: Arc<dyn Reporter>,
    written_files: AtomicUsize,
    copied: AtomicU64,
    downloaded: AtomicU64,
}

enum ProcErr {
    Corrupt(String),
    Io(anyhow::Error),
}

impl Exec {
    fn final_path(&self, wi: usize) -> PathBuf {
        self.dir.join(&self.m.files[self.work[wi].file].path)
    }

    fn write_path(&self, wi: usize) -> PathBuf {
        let p = self.final_path(wi);
        if self.work[wi].in_place {
            p
        } else {
            part_path(&p)
        }
    }

    /// Файл для записи открывается (и при необходимости создаётся нужного размера) при первой
    /// записи в него: заранее создавать десятки тысяч .nwpart — долгие секунды простоя.
    fn handle(&self, wi: usize) -> Result<Arc<File>> {
        let mut h = self.handles.lock();
        if let Some(f) = h.get(&wi) {
            return Ok(f.clone());
        }
        let wp = self.write_path(wi);
        if let Some(par) = wp.parent() {
            fs::create_dir_all(par).with_context(|| format!("создание папки {}", par.display()))?;
        }
        let f = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(false)
            .open(&wp)
            .with_context(|| format!("открытие {}", wp.display()))?;
        let size = self.m.files[self.work[wi].file].size;
        if f.metadata()?.len() != size {
            f.set_len(size)?;
        }
        let f = Arc::new(f);
        h.insert(wi, f.clone());
        Ok(f)
    }

    fn write(&self, t: Target, data: &[u8]) -> Result<()> {
        let f = self.handle(t.work)?;
        pwrite(&f, data, t.offset).with_context(|| format!("запись {}", self.write_path(t.work).display()))?;
        drop(f);
        self.ctr.done.fetch_add(data.len() as u64, Relaxed);
        if self.work[t.work].remaining.fetch_sub(1, AcqRel) == 1 {
            if self.defer.load(Acquire) {
                self.deferred.lock().push(t.work);
            } else {
                self.finalize(t.work)?;
            }
        }
        Ok(())
    }

    fn finalize(&self, wi: usize) -> Result<()> {
        self.handles.lock().remove(&wi);
        let p = self.final_path(wi);
        let w = &self.work[wi];
        let f = &self.m.files[w.file];
        if !w.in_place {
            rename_retry(&part_path(&p), &p).with_context(|| format!("не удалось заменить {} (файл занят?)", p.display()))?;
        }
        let meta = fs::metadata(&p)?;
        self.index.lock().files.insert(f.path.clone(), IndexEntry { size: f.size, mtime: mtime_of(&meta), hash: f.hash });
        self.ctr.files_done.fetch_add(1, Relaxed);
        self.written_files.fetch_add(1, Relaxed);
        self.rep.log(&format!("✓ {}", f.path));
        Ok(())
    }

    fn run_copies(&self, groups: &[(PathBuf, Vec<(u64, u32, Vec<Target>)>)], cancel: &AtomicBool, pool: &rayon::ThreadPool) -> Result<Vec<(u32, Vec<Target>)>> {
        let fallback = Mutex::new(Vec::new());
        pool.install(|| {
            groups.par_iter().try_for_each(|(src, items)| -> Result<()> {
                let f = match File::open(src) {
                    Ok(f) => f,
                    Err(_) => {
                        fallback.lock().extend(items.iter().map(|(_, ci, t)| (*ci, t.clone())));
                        return Ok(());
                    }
                };
                let mut buf = Vec::new();
                for (off, ci, targets) in items {
                    if cancel.load(Relaxed) {
                        bail!(CANCELLED);
                    }
                    let c = &self.m.chunks[*ci as usize];
                    buf.resize(c.size as usize, 0);
                    if pread(&f, &mut buf, *off).is_err() || blake3::hash(&buf).as_bytes() != &c.hash {
                        fallback.lock().push((*ci, targets.clone()));
                        continue;
                    }
                    for t in targets {
                        self.write(*t, &buf)?;
                    }
                    self.copied.fetch_add(c.size as u64 * targets.len() as u64, Relaxed);
                }
                Ok(())
            })
        })?;
        Ok(fallback.into_inner())
    }

    fn process(&self, ci: u32, data: &[u8], zstd: bool) -> std::result::Result<(), ProcErr> {
        let c = &self.m.chunks[ci as usize];
        let raw: Cow<[u8]> = if zstd {
            Cow::Owned(zstd::bulk::decompress(data, c.size as usize).map_err(|e| ProcErr::Corrupt(format!("zstd: {e}")))?)
        } else {
            Cow::Borrowed(data)
        };
        if raw.len() != c.size as usize || blake3::hash(&raw).as_bytes() != &c.hash {
            return Err(ProcErr::Corrupt("контрольная сумма чанка не совпала".into()));
        }
        let targets = self.downloads.read().get(&ci).cloned().unwrap_or_default();
        for t in targets {
            self.write(t, &raw).map_err(ProcErr::Io)?;
        }
        self.downloaded.fetch_add(c.size as u64, Relaxed);
        Ok(())
    }
}

struct Job {
    pack: u32,
    chunks: VecDeque<u32>,
    attempts: u32,
}

struct Dl {
    ex: Arc<Exec>,
    src: Arc<Sources>,
    opts: Options,
    queue: Mutex<VecDeque<Job>>,
    mirror_only: Mutex<VecDeque<Job>>,
    outstanding: AtomicUsize,
    fatal: Mutex<Option<anyhow::Error>>,
    sem: Arc<tokio::sync::Semaphore>,
    cancel: Arc<AtomicBool>,
    mirror_fail: Vec<AtomicU32>,
}

fn backoff(a: u32) -> Duration {
    Duration::from_millis((500u64 << a.saturating_sub(1).min(5)).min(15_000))
}

impl Dl {
    fn stopped(&self) -> bool {
        self.cancel.load(Relaxed) || self.fatal.lock().is_some()
    }

    fn pick_mirror(&self, worker: usize, attempts: u32) -> usize {
        let n = self.src.len();
        // Зеркала с меньшим числом ошибок в приоритете; попытки сдвигают выбор.
        let mut order: Vec<usize> = (0..n).collect();
        order.sort_by_key(|&i| (self.mirror_fail[i].load(Relaxed), (i + n - worker % n) % n));
        order[attempts as usize % n]
    }

    fn pop_job(&self, mirror_worker: bool) -> Option<Job> {
        if mirror_worker {
            if let Some(j) = self.mirror_only.lock().pop_front() {
                return Some(j);
            }
        }
        self.queue.lock().pop_front()
    }

    /// Чанки одного pack-файла → задания для зеркал (соседние склеиваются в один Range).
    fn push_mirror_jobs(&self, pack: u32, mut ids: Vec<u32>, attempts: u32) {
        let m = &self.ex.m;
        ids.sort_by_key(|&c| m.chunks[c as usize].offset);
        let mut q = self.mirror_only.lock();
        let mut cur: Option<(Job, u64, u64)> = None;
        for c in ids {
            let ch = &m.chunks[c as usize];
            let (cs, ce) = (ch.offset, ch.offset + ch.csize as u64);
            match cur.as_mut() {
                Some((j, start, end)) if cs >= *end && cs - *end <= self.opts.gap && ce - *start <= self.opts.range_max => {
                    j.chunks.push_back(c);
                    *end = ce;
                }
                _ => {
                    if let Some((j, _, _)) = cur.take() {
                        q.push_back(j);
                    }
                    cur = Some((Job { pack, chunks: VecDeque::from([c]), attempts }, cs, ce));
                }
            }
        }
        if let Some((j, _, _)) = cur {
            q.push_back(j);
        }
    }

    async fn worker(self: Arc<Self>, id: usize) {
        loop {
            if self.stopped() {
                return;
            }
            let Some(mut job) = self.pop_job(true) else {
                if self.outstanding.load(Acquire) == 0 {
                    return;
                }
                tokio::time::sleep(Duration::from_millis(50)).await;
                continue;
            };
            let mirror = self.pick_mirror(id, job.attempts);
            if let Err(e) = self.fetch(&mut job, mirror).await {
                if self.cancel.load(Relaxed) {
                    return;
                }
                self.mirror_fail[mirror].fetch_add(1, Relaxed);
                if job.chunks.is_empty() {
                    continue;
                }
                job.attempts += 1;
                if job.attempts > self.opts.max_retries {
                    *self.fatal.lock() = Some(e.context("загрузка не удалась после всех попыток"));
                    return;
                }
                self.ex.rep.log(&format!("⚠ {e:#} — повтор {}/{}", job.attempts, self.opts.max_retries));
                tokio::time::sleep(backoff(job.attempts)).await;
                self.queue.lock().push_back(job);
            }
        }
    }

    /// Качает у другого игрока. Чего у него нет — уходит зеркалам.
    async fn peer_worker(self: Arc<Self>, peer: crate::p2p::EndpointId) {
        let Some(node) = self.src.node().cloned() else { return };
        let mut fails = 0;
        loop {
            if self.stopped() {
                return;
            }
            let Some(mut job) = self.pop_job(false) else { return };
            match self.fetch_peer(&node, peer, &mut job).await {
                Ok(missing) => {
                    fails = 0;
                    if !missing.is_empty() {
                        self.push_mirror_jobs(job.pack, missing, job.attempts);
                    }
                    if !job.chunks.is_empty() {
                        self.queue.lock().push_front(job);
                    }
                }
                Err(_) => {
                    if !job.chunks.is_empty() {
                        self.queue.lock().push_back(job);
                    }
                    fails += 1;
                    if fails >= 3 {
                        return;
                    }
                    tokio::time::sleep(Duration::from_secs(1)).await;
                }
            }
        }
    }

    async fn fetch_peer(self: &Arc<Self>, node: &crate::p2p::P2pNode, peer: crate::p2p::EndpointId, job: &mut Job) -> Result<Vec<u32>> {
        let m = &self.ex.m;
        // Пачками: игрок принимает ограниченное число хешей за запрос, остаток вернётся в очередь.
        let ids: Vec<u32> = job.chunks.iter().copied().take(256).collect();
        let hashes: Vec<Hash> = ids.iter().map(|&c| m.chunks[c as usize].hash).collect();
        let stall = self.opts.stall_timeout;
        let mut r = tokio::time::timeout(stall, node.chunks(peer, &hashes)).await.map_err(|_| anyhow!("игрок не отвечает"))??;
        let mut missing = Vec::new();
        for &ci in &ids {
            if self.stopped() {
                bail!(CANCELLED);
            }
            let max = m.chunks[ci as usize].size + 1024;
            let (kind, data) = tokio::time::timeout(stall, crate::p2p::read_chunk_frame(&mut r, max))
                .await
                .map_err(|_| anyhow!("игрок перестал отвечать"))??;
            job.chunks.pop_front();
            self.ex.ctr.net.fetch_add(data.len() as u64, Relaxed);
            self.ex.ctr.net_peers.fetch_add(data.len() as u64, Relaxed);
            if kind == 0 {
                missing.push(ci);
                continue;
            }
            self.spawn_process(ci, bytes::Bytes::from(data), kind == 2, job.pack, job.attempts, None).await?;
        }
        Ok(missing)
    }

    async fn spawn_process(self: &Arc<Self>, ci: u32, data: bytes::Bytes, zstd: bool, pack: u32, attempts: u32, mirror: Option<usize>) -> Result<()> {
        let permit = self.sem.clone().acquire_owned().await?;
        let me = self.clone();
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            match me.ex.process(ci, &data, zstd) {
                Ok(()) => {
                    me.outstanding.fetch_sub(1, AcqRel);
                }
                Err(ProcErr::Corrupt(msg)) => {
                    if let Some(mi) = mirror {
                        me.mirror_fail[mi % me.mirror_fail.len()].fetch_add(1, Relaxed);
                    }
                    if attempts + 1 > me.opts.max_retries {
                        *me.fatal.lock() = Some(anyhow!("чанк повреждён на всех источниках: {msg}"));
                    } else {
                        me.ex.rep.log(&format!("⚠ {msg} — перекачиваю"));
                        me.mirror_only.lock().push_back(Job { pack, chunks: VecDeque::from([ci]), attempts: attempts + 1 });
                    }
                }
                Err(ProcErr::Io(e)) => {
                    *me.fatal.lock() = Some(e);
                }
            }
        });
        Ok(())
    }

    async fn fetch(self: &Arc<Self>, job: &mut Job, mirror: usize) -> Result<()> {
        let m = &self.ex.m;
        let first = m.chunks[*job.chunks.front().unwrap() as usize].offset;
        let last = &m.chunks[*job.chunks.back().unwrap() as usize];
        let end = last.offset + last.csize as u64;
        let rel = &m.packs[job.pack as usize];
        let stall = self.opts.stall_timeout;
        let mut stream = tokio::time::timeout(stall, self.src.range(mirror, rel, first, end))
            .await
            .map_err(|_| anyhow!("таймаут подключения"))??;
        let mut buf = BytesMut::new();
        let mut pos = first;
        while let Some(&ci) = job.chunks.front() {
            let c = &m.chunks[ci as usize];
            let cend = c.offset + c.csize as u64;
            if pos + (buf.len() as u64) < cend {
                if self.stopped() {
                    bail!(CANCELLED);
                }
                match tokio::time::timeout(stall, stream.next()).await {
                    Err(_) => bail!("нет данных {} с", stall.as_secs()),
                    Ok(Some(Ok(b))) => {
                        self.ex.ctr.net.fetch_add(b.len() as u64, Relaxed);
                        buf.extend_from_slice(&b);
                    }
                    Ok(Some(Err(e))) => return Err(e),
                    Ok(None) => bail!("сервер закрыл соединение раньше времени"),
                }
                continue;
            }
            let skip = (c.offset - pos) as usize;
            let _ = buf.split_to(skip);
            let data = buf.split_to(c.csize as usize).freeze();
            pos = cend;
            job.chunks.pop_front();
            self.spawn_process(ci, data, c.zstd, job.pack, job.attempts, Some(mirror)).await?;
        }
        Ok(())
    }
}

impl Engine {
    async fn find_peers(&self, manifest_hash: &str) -> Vec<crate::p2p::EndpointId> {
        let Some(node) = self.sources.node().cloned() else { return vec![] };
        let mut out = Vec::new();
        for s in self.sources.p2p_servers() {
            if let Ok(Ok(list)) = tokio::time::timeout(Duration::from_secs(10), node.peers(s, manifest_hash)).await {
                for p in list {
                    if !out.contains(&p) && p != s {
                        out.push(p);
                    }
                }
            }
        }
        out.truncate(24);
        out
    }

    fn user_set(&self) -> Result<globset::GlobSet> {
        crate::local::glob_set(&self.opts.user_files)
    }

    fn keep_set(&self) -> Result<globset::GlobSet> {
        let mut b = globset::GlobSetBuilder::new();
        for k in &self.opts.keep {
            b.add(globset::GlobBuilder::new(k).case_insensitive(true).literal_separator(false).build()?);
        }
        Ok(b.build()?)
    }

    fn spawn_ticker(&self, ctr: Arc<Ctr>, stop: Arc<AtomicBool>) -> tokio::task::JoinHandle<()> {
        let rep = self.rep.clone();
        tokio::spawn(async move {
            let mut last = Instant::now();
            let mut last_bytes = 0u64;
            let mut last_phase = String::new();
            let mut ema = 0.0f64;
            loop {
                tokio::time::sleep(Duration::from_millis(250)).await;
                let finished = stop.load(Acquire);
                let (phase, text) = ctr.phase.lock().clone();
                let net_total = ctr.net_total.load(Relaxed);
                let downloading = phase == "download";
                let cur = if downloading { ctr.net.load(Relaxed) } else { ctr.done.load(Relaxed) };
                if phase != last_phase {
                    last_phase = phase.clone();
                    last_bytes = cur;
                    ema = 0.0;
                }
                let dt = last.elapsed().as_secs_f64().max(0.001);
                let inst = cur.saturating_sub(last_bytes) as f64 / dt;
                ema = if ema == 0.0 { inst } else { ema * 0.85 + inst * 0.15 };
                last = Instant::now();
                last_bytes = cur;
                let (done, total) = (ctr.done.load(Relaxed), ctr.total.load(Relaxed));
                let left = if downloading { net_total.saturating_sub(cur) } else { total.saturating_sub(done) };
                rep.progress(&Progress {
                    phase,
                    text,
                    done,
                    total,
                    net_done: ctr.net.load(Relaxed).min(net_total),
                    net_total,
                    net_peers: ctr.net_peers.load(Relaxed),
                    peers: ctr.peers.load(Relaxed),
                    speed: ema,
                    eta: (ema > 1.0).then(|| (left as f64 / ema) as u64),
                    files_done: ctr.files_done.load(Relaxed),
                    files_total: ctr.files_total.load(Relaxed),
                });
                if finished {
                    return;
                }
            }
        })
    }

    /// Привести папку игры к манифесту. `verify_all` — перехешировать всё («Проверить файлы»).
    pub async fn sync(&self, m: Arc<Manifest>, manifest_bytes: &[u8], release: &Release, verify_all: bool) -> Result<Summary> {
        let t0 = Instant::now();
        fs::create_dir_all(&self.dir).with_context(|| format!("создание {}", self.dir.display()))?;
        let _lock = DirLock::acquire(&self.dir)?;
        let ctr = Arc::new(Ctr::default());
        ctr.phase("prepare", "Подготовка", 0, 0);
        let stop = Arc::new(AtomicBool::new(false));
        let ticker = self.spawn_ticker(ctr.clone(), stop.clone());
        let res = self.sync_inner(m, manifest_bytes, release, verify_all, ctr).await;
        stop.store(true, Release_);
        let _ = ticker.await;
        res.map(|mut s| {
            s.seconds = t0.elapsed().as_secs_f64();
            s
        })
    }

    async fn sync_inner(&self, m: Arc<Manifest>, manifest_bytes: &[u8], release: &Release, verify_all: bool, ctr: Arc<Ctr>) -> Result<Summary> {
        let local = Local::new(&self.dir);
        let old = local.load_manifest().map(Arc::new);
        let installed = local.installed();
        let threads = if self.opts.verify_threads == 0 {
            std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).min(12)
        } else {
            self.opts.verify_threads
        };
        let pool = Arc::new(rayon::ThreadPoolBuilder::new().num_threads(threads).build()?);
        let keep = self.keep_set()?;
        let user = self.user_set()?;
        let rep = self.rep.clone();

        rep.log(&format!(
            "{} версии {}: {} файлов, {}",
            if verify_all { "Полная проверка" } else { "Синхронизация" },
            m.version,
            m.files.len(),
            human_bytes(m.total_size())
        ));

        let plan = {
            let (dir, m, old, cancel, ctr, pool) = (self.dir.clone(), m.clone(), old.clone(), self.cancel.clone(), ctr.clone(), pool.clone());
            let index = local.load_index();
            tokio::task::spawn_blocking(move || plan(&dir, &m, old.as_deref(), index, verify_all, &keep, &user, &ctr, &cancel, &pool)).await??
        };

        let dl_bytes: u64 = plan.downloads.iter().map(|(ci, t)| m.chunks[*ci as usize].size as u64 * t.len() as u64).sum();
        let copy_bytes: u64 = plan.copies.iter().flat_map(|(_, v)| v.iter()).map(|(_, ci, t)| m.chunks[*ci as usize].size as u64 * t.len() as u64).sum();
        let net_need: u64 = plan.downloads.keys().map(|ci| m.chunks[*ci as usize].csize as u64).sum();
        if plan.verified_ok > 0 {
            rep.log(&format!("Проверено и в порядке: {} файлов", plan.verified_ok));
        }
        if !plan.work.is_empty() {
            rep.log(&format!(
                "Нужно обновить {} файлов: скачать {}, собрать локально {}",
                plan.work.len(),
                human_bytes(net_need),
                human_bytes(copy_bytes)
            ));
        }

        if let Some(free) = free_space(&self.dir) {
            let need = plan.new_part_bytes + (64 << 20);
            if free < need {
                bail!("Недостаточно места на диске: нужно {}, свободно {}", human_bytes(need), human_bytes(free));
            }
        }

        let work_len = plan.work.len() as u64;
        let ex = Arc::new(Exec {
            dir: self.dir.clone(),
            m: m.clone(),
            work: plan.work,
            handles: Mutex::new(HashMap::new()),
            index: Mutex::new(plan.index),
            defer: AtomicBool::new(true),
            deferred: Mutex::new(plan.ready),
            downloads: RwLock::new(plan.downloads),
            ctr: ctr.clone(),
            rep: rep.clone(),
            written_files: AtomicUsize::new(0),
            copied: AtomicU64::new(0),
            downloaded: AtomicU64::new(0),
        });

        let result = self.execute(&ex, plan.copies, copy_bytes, dl_bytes, work_len, pool, &release.manifest_hash).await;
        // Индекс сохраняем всегда: при отмене/ошибке готовые файлы не придётся проверять заново.
        ex.handles.lock().clear();
        let index = ex.index.lock().clone();
        local.save_index(&index)?;
        result?;

        ctr.phase("finish", "Завершение", 0, 0);
        let mut deleted = 0;
        for p in &plan.delete {
            let full = self.dir.join(p);
            let _ = fs::remove_file(part_path(&full));
            if fs::remove_file(&full).is_ok() {
                deleted += 1;
                rep.log(&format!("🗑 {p}"));
                let mut d = full.parent();
                while let Some(dd) = d {
                    if dd == self.dir || fs::remove_dir(dd).is_err() {
                        break;
                    }
                    d = dd.parent();
                }
            }
        }
        let mut index = index;
        for p in &plan.delete {
            index.files.remove(p);
        }
        if installed.as_ref().map(|i| i.version.as_str()) != Some(release.version.as_str()) {
            for d in &self.opts.clean_on_update {
                let p = self.dir.join(d);
                if p.is_dir() && fs::remove_dir_all(&p).is_ok() {
                    rep.log(&format!("Очищено: {d}"));
                }
            }
        }
        local.save_index(&index)?;
        local.save_manifest(manifest_bytes)?;
        local.save_installed(&Installed { version: release.version.clone(), manifest_hash: release.manifest_hash.clone(), updated: now_unix() })?;

        Ok(Summary {
            version: release.version.clone(),
            downloaded: ex.downloaded.load(Relaxed),
            network: ctr.net.load(Relaxed),
            from_peers: ctr.net_peers.load(Relaxed),
            copied: ex.copied.load(Relaxed),
            written_files: ex.written_files.load(Relaxed),
            verified_ok: plan.verified_ok,
            deleted,
            seconds: 0.0,
        })
    }

    async fn execute(
        &self,
        ex: &Arc<Exec>,
        copies: Vec<(PathBuf, Vec<(u64, u32, Vec<Target>)>)>,
        copy_bytes: u64,
        dl_bytes: u64,
        work_len: u64,
        pool: Arc<rayon::ThreadPool>,
        manifest_hash: &str,
    ) -> Result<()> {
        // Копирование: пока идёт, старые файлы ещё на месте, поэтому замены (rename) откладываем.
        if copy_bytes > 0 {
            ex.ctr.phase("copy", "Сборка из локальных данных", copy_bytes, work_len);
            let (ex2, cancel) = (ex.clone(), self.cancel.clone());
            let fallback = tokio::task::spawn_blocking(move || ex2.run_copies(&copies, &cancel, &pool)).await??;
            if !fallback.is_empty() {
                let mut d = ex.downloads.write();
                for (ci, t) in fallback {
                    d.entry(ci).or_default().extend(t);
                }
            }
        }
        ex.defer.store(false, Release_);
        let ready: Vec<usize> = std::mem::take(&mut *ex.deferred.lock());
        {
            let ex = ex.clone();
            tokio::task::spawn_blocking(move || ready.into_iter().try_for_each(|wi| ex.finalize(wi))).await??;
        }

        let n_dl = ex.downloads.read().len();
        if n_dl == 0 {
            return Ok(());
        }
        let total_raw: u64 = {
            let d = ex.downloads.read();
            d.iter().map(|(ci, t)| ex.m.chunks[*ci as usize].size as u64 * t.len() as u64).sum::<u64>().max(dl_bytes)
        };
        let mut by_pack: HashMap<u32, Vec<u32>> = HashMap::new();
        for &ci in ex.downloads.read().keys() {
            by_pack.entry(ex.m.chunks[ci as usize].pack).or_default().push(ci);
        }
        let mut packs: Vec<_> = by_pack.into_iter().collect();
        packs.sort_by_key(|(p, _)| *p);
        let mut jobs = VecDeque::new();
        let mut net_total = 0u64;
        for (pack, mut ids) in packs {
            ids.sort_by_key(|&c| ex.m.chunks[c as usize].offset);
            let mut cur: Option<Job> = None;
            let (mut start, mut end) = (0u64, 0u64);
            for c in ids {
                let ch = &ex.m.chunks[c as usize];
                let (cs, ce) = (ch.offset, ch.offset + ch.csize as u64);
                match cur.as_mut() {
                    Some(j) if cs >= end && cs - end <= self.opts.gap && ce - start <= self.opts.range_max => {
                        j.chunks.push_back(c);
                        end = ce;
                    }
                    _ => {
                        if let Some(j) = cur.take() {
                            net_total += end - start;
                            jobs.push_back(j);
                        }
                        cur = Some(Job { pack, chunks: VecDeque::from([c]), attempts: 0 });
                        start = cs;
                        end = ce;
                    }
                }
            }
            if let Some(j) = cur {
                net_total += end - start;
                jobs.push_back(j);
            }
        }

        ex.ctr.phase("download", "Загрузка", total_raw, work_len);
        ex.ctr.net.store(0, Relaxed);
        ex.ctr.net_total.store(net_total, Relaxed);
        let permits = (std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4) * 2).max(8);
        let dl = Arc::new(Dl {
            ex: ex.clone(),
            src: self.sources.clone(),
            opts: self.opts.clone(),
            outstanding: AtomicUsize::new(n_dl),
            queue: Mutex::new(jobs),
            mirror_only: Mutex::new(VecDeque::new()),
            fatal: Mutex::new(None),
            sem: Arc::new(tokio::sync::Semaphore::new(permits)),
            cancel: self.cancel.clone(),
            mirror_fail: (0..self.sources.len()).map(|_| AtomicU32::new(0)).collect(),
        });
        let mut set = tokio::task::JoinSet::new();
        // Игроки, у которых эта версия уже есть, раздают её как в торренте.
        // Их запускаем первыми: сервер (обычно домашний ПК) разгружается сильнее.
        if self.opts.use_peers {
            let peers = self.find_peers(manifest_hash).await;
            if !peers.is_empty() {
                self.rep.log(&format!("Раздают игроки: {}", peers.len()));
                ex.ctr.peers.store(peers.len() as u32, Relaxed);
                for p in peers {
                    for _ in 0..2 {
                        set.spawn(dl.clone().peer_worker(p));
                    }
                }
                tokio::time::sleep(Duration::from_millis(300)).await;
            }
        }
        for w in 0..self.opts.connections.max(1) {
            set.spawn(dl.clone().worker(w));
        }
        while let Some(r) = set.join_next().await {
            r?;
        }
        // Дождаться обработки уже скачанных чанков.
        let _all = dl.sem.acquire_many(permits as u32).await?;
        if let Some(e) = dl.fatal.lock().take() {
            return Err(e);
        }
        if self.cancel.load(Relaxed) {
            bail!(CANCELLED);
        }
        if dl.outstanding.load(Acquire) != 0 {
            bail!("загрузка прервана: остались необработанные чанки");
        }
        Ok(())
    }
}

#[allow(non_upper_case_globals)]
const Release_: std::sync::atomic::Ordering = std::sync::atomic::Ordering::Release;

/// Эксклюзивная блокировка папки: два процесса не должны писать в одну установку.
/// Файл открыт без общего доступа — Windows снимет блокировку сама, даже если процесс убит.
struct DirLock {
    _f: File,
}

impl DirLock {
    fn acquire(dir: &Path) -> Result<Self> {
        let p = dir.join(crate::local::STATE_DIR).join("sync.lock");
        fs::create_dir_all(p.parent().unwrap())?;
        let mut o = OpenOptions::new();
        o.write(true).create(true).truncate(false);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            o.share_mode(0);
        }
        match o.open(&p) {
            Ok(f) => Ok(Self { _f: f }),
            Err(_) => bail!("Папку игры уже обновляет другой процесс (второй лаунчер?)"),
        }
    }
}
