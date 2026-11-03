//! Режим установщика и удаление.

use crate::brand::Brand;
use crate::sys;
use gamesync::local::Local;
use gamesync::util::{free_space, human_bytes};
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use tauri::AppHandle;

pub struct SetupSt {
    pub brand: Brand,
}

type S<'a> = tauri::State<'a, Arc<SetupSt>>;

#[derive(Serialize)]
pub struct SetupInfo {
    product: String,
    title: String,
    version: String,
    default_dir: String,
    existing: bool,
    text: String,
    game_size: Option<u64>,
}

#[tauri::command]
pub async fn setup_info(st: S<'_>) -> Result<SetupInfo, String> {
    let b = st.brand.clone();
    let reg = sys::registered_location(&b.product);
    let existing = reg.as_ref().map(|p| p.join(".launcher").exists()).unwrap_or(false);
    let dir = reg.filter(|_| existing).unwrap_or_else(|| PathBuf::from(&b.default_install_dir));
    // Размер игры — с сервера, если он доступен (не обязательно).
    let game_size = match gamesync::Sources::new(&b.base_urls, Duration::from_secs(4)) {
        Ok(s) => tokio::time::timeout(Duration::from_secs(5), gamesync::fetch_release(&s, &b.public_key))
            .await
            .ok()
            .and_then(|r| r.ok())
            .map(|r| r.game_size),
        Err(_) => None,
    };
    Ok(SetupInfo {
        product: b.product,
        title: b.title,
        version: crate::launcher::VERSION.into(),
        default_dir: dir.to_string_lossy().into(),
        existing,
        text: b.setup_text,
        game_size,
    })
}

#[derive(Serialize)]
pub struct DirInfo {
    free: Option<u64>,
    free_text: String,
    has_game: bool,
    message: String,
}

#[tauri::command]
pub fn dir_info(st: S<'_>, path: String) -> DirInfo {
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
    DirInfo {
        free,
        free_text: free.map(|f| format!("Свободно на {drive} {}", human_bytes(f))).unwrap_or_default(),
        has_game,
        message,
    }
}

#[tauri::command]
pub async fn pick_dir(current: String) -> Option<String> {
    tokio::task::spawn_blocking(move || {
        let mut d = rfd::FileDialog::new().set_title("Папка установки");
        let cur = PathBuf::from(&current);
        if let Some(existing) = cur.ancestors().find(|a| a.is_dir()) {
            d = d.set_directory(existing);
        }
        d.pick_folder().map(|p| p.to_string_lossy().to_string())
    })
    .await
    .ok()
    .flatten()
}

#[tauri::command]
pub async fn do_install(app: AppHandle, st: S<'_>, path: String, desktop: bool, start_menu: bool, launch: bool) -> Result<(), String> {
    let b = st.brand.clone();
    let res = tokio::task::spawn_blocking(move || install(&b, Path::new(&path), desktop, start_menu, launch)).await.map_err(|e| e.to_string())?;
    match res {
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

fn install(b: &Brand, dir: &Path, desktop: bool, start_menu: bool, launch: bool) -> anyhow::Result<bool> {
    if !dir.is_absolute() {
        anyhow::bail!("Укажите полный путь к папке");
    }
    std::fs::create_dir_all(dir.join(".launcher"))?;
    let me = std::env::current_exe()?;
    let target = dir.join(&b.exe_name);
    if me != target {
        if target.exists() {
            let old = target.with_extension("exe.old");
            let _ = std::fs::remove_file(&old);
            std::fs::rename(&target, &old).map_err(|e| anyhow::anyhow!("Закройте лаунчер и повторите ({e})"))?;
        }
        std::fs::copy(&me, &target)?;
    }
    std::fs::write(
        dir.join(".launcher").join("install.json"),
        serde_json::to_vec_pretty(&serde_json::json!({
            "product": b.product,
            "launcher": crate::launcher::VERSION,
            "installed": gamesync::local::now_unix(),
        }))?,
    )?;
    sys::register_uninstall(&b.product, &b.publisher, crate::launcher::VERSION, dir, &target)?;
    if desktop {
        if let Some(l) = sys::desktop_lnk(&b.product) {
            sys::create_shortcut(&l, &target, "", dir, &b.product)?;
        }
    }
    if start_menu {
        if let Some(d) = sys::start_menu_dir(&b.product) {
            sys::create_shortcut(&d.join(format!("{}.lnk", b.product)), &target, "", dir, &b.product)?;
            sys::create_shortcut(&d.join(format!("Удалить {}.lnk", b.product)), &target, "--uninstall", dir, "Удаление")?;
        }
    }
    if launch {
        std::process::Command::new(&target).current_dir(dir).spawn()?;
    }
    Ok(launch)
}

pub fn uninstall(b: &Brand, dir: &Path) {
    use rfd::{MessageButtons, MessageDialog, MessageDialogResult, MessageLevel};
    let ask = |title: &str, text: &str| {
        MessageDialog::new().set_level(MessageLevel::Warning).set_title(title).set_description(text).set_buttons(MessageButtons::YesNo).show()
            == MessageDialogResult::Yes
    };
    if !ask(&format!("Удаление {}", b.product), &format!("Удалить {} из {}?", b.product, dir.display())) {
        return;
    }
    let manifest = Local::new(dir).load_manifest();
    let size: u64 = manifest.as_ref().map(|m| m.total_size()).unwrap_or(0);
    let wipe_game = manifest.is_some()
        && ask(
            &format!("Удаление {}", b.product),
            &format!("Удалить также файлы игры ({})?\n\n«Нет» — оставить их: при переустановке в эту же папку ничего не придётся качать заново.", human_bytes(size)),
        );

    if let Some(l) = sys::desktop_lnk(&b.product) {
        let _ = std::fs::remove_file(l);
    }
    if let Some(d) = sys::start_menu_dir(&b.product) {
        let _ = std::fs::remove_dir_all(d);
    }
    sys::unregister_uninstall(&b.product);

    if wipe_game {
        if let Some(m) = &manifest {
            for f in &m.files {
                let p = dir.join(&f.path);
                let _ = std::fs::remove_file(gamesync::local::part_path(&p));
                let _ = std::fs::remove_file(&p);
            }
        }
        let _ = std::fs::remove_dir_all(dir.join(".launcher"));
        remove_empty_dirs(dir);
    } else {
        let _ = std::fs::remove_file(dir.join(".launcher").join("install.json"));
    }
    let me = std::env::current_exe().unwrap_or_else(|_| dir.join(&b.exe_name));
    sys::delete_after_exit(&me, wipe_game.then_some(dir));
    MessageDialog::new()
        .set_title(&b.product)
        .set_description(if wipe_game { "Удаление завершено." } else { "Лаунчер удалён. Файлы игры оставлены на месте." })
        .set_buttons(MessageButtons::Ok)
        .show();
}

fn remove_empty_dirs(dir: &Path) {
    if let Ok(rd) = std::fs::read_dir(dir) {
        for e in rd.flatten() {
            if e.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                remove_empty_dirs(&e.path());
                let _ = std::fs::remove_dir(e.path());
            }
        }
    }
}
