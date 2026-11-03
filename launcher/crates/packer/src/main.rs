//! packer — консольные инструменты издателя.
//!
//!   packer keygen  --out keys
//!   packer pack    --input <папка игры> --out <publish> --version 1.0.0 --key keys/secret.key
//!   packer serve   --dir <publish> --port 8080                     (HTTP-зеркало)
//!   packer install --url p2p://<ключ> --dir <куда> --pubkey <hex>   (тестовый клиент)
//!   packer seed    --dir <установка> --url p2p://<ключ>             (раздавать как игрок)

use anyhow::Result;
use clap::{Parser, Subcommand};
use gamesync::util::human_bytes;
use gamesync::{Engine, Options, Progress, Reporter, Sources};
use packer::{PackOptions, PackProgress};
use parking_lot::Mutex;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering::Relaxed};
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Parser)]
#[command(name = "packer", about = "Сборка релизов для лаунчера")]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Создать пару ключей подписи (secret.key храните в секрете!)
    Keygen {
        #[arg(long, default_value = "keys")]
        out: PathBuf,
    },
    /// Упаковать папку игры в релиз
    Pack {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        out: PathBuf,
        #[arg(long)]
        version: String,
        #[arg(long)]
        key: PathBuf,
        #[arg(long, default_value = "NetAnomaly")]
        product: String,
        /// Уровень zstd (1..22). 19 — хорошее сжатие, распаковка всё равно быстрая.
        #[arg(long, default_value_t = 19)]
        level: i32,
        /// Размер pack-файла, МБ
        #[arg(long, default_value_t = 256)]
        pack_mb: u64,
        /// Исключить пути (glob), можно несколько раз
        #[arg(long)]
        exclude: Vec<String>,
        /// exe лаунчера для автообновления
        #[arg(long)]
        launcher: Option<PathBuf>,
        #[arg(long)]
        launcher_version: Option<String>,
        /// Перечитать все файлы, не доверяя кешу (размер + время изменения)
        #[arg(long)]
        rescan: bool,
    },
    /// Выложить новый лаунчер (без перепаковки игры)
    Launcher {
        #[arg(long)]
        out: PathBuf,
        #[arg(long)]
        exe: PathBuf,
        /// Необязательно: по умолчанию берётся из exe
        #[arg(long, default_value = "")]
        version: String,
        #[arg(long)]
        key: PathBuf,
    },
    /// HTTP-зеркало с поддержкой Range (для белого IP или хостинга)
    Serve {
        #[arg(long)]
        dir: PathBuf,
        #[arg(long, default_value_t = 8080)]
        port: u16,
    },
    /// Консольная установка/обновление (тесты, выделенные серверы)
    Install {
        #[arg(long, required = true)]
        url: Vec<String>,
        #[arg(long)]
        dir: PathBuf,
        #[arg(long)]
        pubkey: String,
        #[arg(long)]
        verify: bool,
        #[arg(long, default_value_t = 16)]
        connections: usize,
        /// Не качать у игроков, только с сервера
        #[arg(long)]
        no_peers: bool,
        /// Только через relay: никто не узнает ваш IP
        #[arg(long)]
        hide_ip: bool,
    },
    /// Раздавать установленную игру другим игрокам (как лаунчер в фоне)
    Seed {
        #[arg(long)]
        dir: PathBuf,
        #[arg(long, required = true)]
        url: Vec<String>,
        /// Только через relay: никто не узнает ваш IP
        #[arg(long)]
        hide_ip: bool,
    },
}

fn main() -> Result<()> {
    match Cli::parse().cmd {
        Cmd::Keygen { out } => {
            let pk = packer::keygen(&out)?;
            println!("Ключи созданы в {}", out.display());
            println!("public_key для brand.json: {pk}");
            Ok(())
        }
        Cmd::Pack { input, out, version, key, product, level, pack_mb, exclude, launcher, launcher_version, rescan } => {
            let secret_key = std::fs::read_to_string(&key).map_err(|e| anyhow::anyhow!("чтение ключа {}: {e}", key.display()))?;
            let o = PackOptions { input, out, version, secret_key, product, level, pack_size: pack_mb << 20, exclude, launcher, launcher_version, rescan };
            let r = packer::pack(&o, &|p: &PackProgress| {
                print!(
                    "\r  {:>5.1}%  {} / {}  {:.0} МБ/с  новых данных {}      ",
                    p.done as f64 * 100.0 / p.total.max(1) as f64,
                    human_bytes(p.done),
                    human_bytes(p.total),
                    p.speed / 1048576.0,
                    human_bytes(p.new_bytes)
                );
                let _ = std::io::stdout().flush();
            })?;
            println!();
            println!("Готово за {:.0} с", r.seconds);
            println!("  версия          {}", r.version);
            println!("  манифест        {} ({})", r.manifest, human_bytes(r.manifest_size));
            println!("  файлов          {}", r.files);
            println!("  уникальных чанков {} (объём на сервере {})", r.chunks, human_bytes(r.server_bytes));
            println!("  новых данных в этом релизе {}", human_bytes(r.new_bytes));
            Ok(())
        }
        Cmd::Launcher { out, exe, version, key } => {
            let secret = std::fs::read_to_string(&key).map_err(|e| anyhow::anyhow!("чтение ключа {}: {e}", key.display()))?;
            let l = packer::publish_launcher(&out, &exe, &version, &secret)?;
            println!("Лаунчер {} опубликован: {} ({})", l.version, l.path, human_bytes(l.size));
            Ok(())
        }
        Cmd::Serve { dir, port } => serve(dir, port),
        Cmd::Install { url, dir, pubkey, verify, connections, no_peers, hide_ip } => install(url, dir, pubkey, verify, connections, no_peers, hide_ip),
        Cmd::Seed { dir, url, hide_ip } => seed(dir, url, hide_ip),
    }
}

fn serve(dir: PathBuf, port: u16) -> Result<()> {
    let rt = tokio::runtime::Runtime::new()?;
    rt.block_on(async move {
        let app = axum::Router::new().fallback_service(tower_http::services::ServeDir::new(&dir));
        let l = tokio::net::TcpListener::bind(("0.0.0.0", port)).await?;
        println!("Раздаю {} на http://127.0.0.1:{port}/", dir.display());
        axum::serve(l, app).await?;
        Ok(())
    })
}

struct Cli2 {
    last: Mutex<Instant>,
}

impl Reporter for Cli2 {
    fn progress(&self, p: &Progress) {
        let mut l = self.last.lock();
        if l.elapsed() < Duration::from_millis(1000) {
            return;
        }
        *l = Instant::now();
        let dl = p.phase == "download";
        let pct = if dl && p.net_total > 0 { p.net_done as f64 / p.net_total as f64 } else { p.done as f64 / p.total.max(1) as f64 };
        println!(
            "  [{}] {:5.1}%  {}/{}  {}/с  ETA {}  файлов {}/{}{}",
            p.text,
            pct * 100.0,
            human_bytes(if dl { p.net_done } else { p.done }),
            human_bytes(if dl { p.net_total } else { p.total }),
            human_bytes(p.speed as u64),
            p.eta.map(|e| format!("{}:{:02}", e / 60, e % 60)).unwrap_or("-".into()),
            p.files_done,
            p.files_total,
            if p.net_peers > 0 { format!("  от игроков {}", human_bytes(p.net_peers)) } else { String::new() }
        );
    }
    fn log(&self, line: &str) {
        if !line.starts_with('✓') {
            println!("{line}");
        }
    }
}

async fn sources_for(url: &[String], hide_ip: bool) -> Result<Arc<Sources>> {
    let sources = Arc::new(Sources::new(url, Duration::from_secs(10))?);
    if sources.has_p2p() {
        let node = gamesync::p2p::P2pNode::bind(None, 4, hide_ip, &gamesync::p2p::default_relays()).await?;
        println!("P2P-узел запущен: {}", node.id());
        sources.set_node(node);
    }
    Ok(sources)
}

fn install(url: Vec<String>, dir: PathBuf, pubkey: String, verify: bool, connections: usize, no_peers: bool, hide_ip: bool) -> Result<()> {
    let rt = tokio::runtime::Runtime::new()?;
    rt.block_on(async move {
        let sources = sources_for(&url, hide_ip).await?;
        let r = gamesync::fetch_release(&sources, &pubkey).await?;
        println!("Сервер: {} {} ({})", r.product, r.version, human_bytes(r.game_size));
        let (m, b) = gamesync::fetch_manifest(&sources, &r).await?;
        let cancel = Arc::new(AtomicBool::new(false));
        {
            let c = cancel.clone();
            tokio::spawn(async move {
                if tokio::signal::ctrl_c().await.is_ok() {
                    println!("\nОтмена…");
                    c.store(true, Relaxed);
                }
            });
        }
        let eng = Engine {
            dir,
            sources: sources.clone(),
            opts: Options { connections, use_peers: !no_peers, ..Default::default() },
            cancel,
            rep: Arc::new(Cli2 { last: Mutex::new(Instant::now()) }),
        };
        let s = eng.sync(m, &b, &r, verify).await?;
        println!(
            "Готово за {:.1} с: скачано {} (по сети {}, из них от игроков {}), собрано локально {}, записано файлов {}, проверено ок {}, удалено {}",
            s.seconds,
            human_bytes(s.downloaded),
            human_bytes(s.network),
            human_bytes(s.from_peers),
            human_bytes(s.copied),
            s.written_files,
            s.verified_ok,
            s.deleted
        );
        if let Some(n) = sources.node() {
            n.shutdown().await;
        }
        Ok(())
    })
}

fn seed(dir: PathBuf, url: Vec<String>, hide_ip: bool) -> Result<()> {
    let rt = tokio::runtime::Runtime::new()?;
    rt.block_on(async move {
        let idx = gamesync::p2p::SeedIndex::build(&dir).ok_or_else(|| anyhow::anyhow!("в {} нет установленной игры", dir.display()))?;
        let (mh, ver) = (idx.manifest_hash.clone(), idx.version.clone());
        println!("Раздаю версию {ver}: {} чанков", idx.chunks());
        let node = gamesync::p2p::P2pNode::bind(None, 8, hide_ip, &gamesync::p2p::default_relays()).await?;
        node.set_provider(Some(Arc::new(idx)));
        println!("P2P-узел: {}", node.id());
        let servers: Vec<_> = url.iter().filter_map(|u| u.strip_prefix("p2p://")).filter_map(|s| gamesync::p2p::parse_id(s).ok()).collect();
        loop {
            for s in &servers {
                match node.announce(*s, &mh, &ver).await {
                    Ok(()) => {}
                    Err(e) => println!("анонс на {}: {e:#}", s.fmt_short()),
                }
            }
            println!("  отдано {}, запросов {}", human_bytes(node.stats.sent.load(Relaxed)), node.stats.requests.load(Relaxed));
            tokio::select! {
                _ = tokio::time::sleep(Duration::from_secs(30)) => {}
                _ = tokio::signal::ctrl_c() => break,
            }
        }
        node.shutdown().await;
        Ok(())
    })
}
