#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod brand;
mod addons;
mod launcher;
mod setup;
mod sys;

use std::path::PathBuf;
use std::sync::Arc;
use tauri::{WebviewUrl, WebviewWindowBuilder};

enum Mode {
    Launcher(PathBuf),
    Setup,
}

fn main() {
    let brand = brand::load();
    let args: Vec<String> = std::env::args().collect();
    let exe = std::env::current_exe().expect("current_exe");
    let exe_dir = exe.parent().expect("exe dir").to_path_buf();
    let arg_val = |k: &str| args.iter().position(|a| a == k).and_then(|i| args.get(i + 1)).cloned();

    if args.iter().any(|a| a == "--uninstall") {
        setup::uninstall(&brand, &exe_dir);
        return;
    }
    // Один exe — три роли: установщик (вне папки игры), лаунчер (в папке установки), удаление.
    let mut master = args.iter().any(|a| a == "--master");
    let mode = if let Some(d) = arg_val("--dir") {
        Mode::Launcher(PathBuf::from(d))
    } else if args.iter().any(|a| a == "--setup") {
        Mode::Setup
    } else if exe_dir.join("runtime-layout.json").is_file()
        && brand.renderers.iter().any(|r| exe_dir.join(&r.exe).is_file()) {
        // A portable player folder is a launcher installation too. No installer
        // marker is required, and it must not accidentally open the setup UI.
        Mode::Launcher(exe_dir.clone())
    } else if let Some(game) = master_copy_next_to(&brand, &exe_dir) {
        // Лаунчер владельца лежит рядом с мастер-копией игры: только запуск, без обновлений.
        master = true;
        Mode::Launcher(game)
    } else if exe_dir.join(".launcher").join("install.json").exists() || args.iter().any(|a| a == "--launcher") {
        Mode::Launcher(exe_dir)
    } else {
        Mode::Setup
    };

    let title = brand.product.clone();
    let mut builder = tauri::Builder::default();
    builder = match &mode {
        Mode::Launcher(dir) => builder.manage(Arc::new(launcher::St::new(brand.clone(), dir.clone(), master))),
        Mode::Setup => builder.manage(Arc::new(setup::SetupSt { brand: brand.clone() })),
    };
    builder
        .invoke_handler(tauri::generate_handler![
            launcher::boot,
            launcher::show_main,
            launcher::info,
            launcher::check_update,
            launcher::start_sync,
            launcher::cancel_sync,
            launcher::save_settings,
            launcher::set_renderer,
            launcher::list_addons,
            launcher::set_addon,
            launcher::play,
            launcher::open_link,
            launcher::news,
            launcher::quit,
            launcher::set_seed,
            setup::setup_info,
            setup::dir_info,
            setup::pick_dir,
            setup::do_install,
        ])
        .setup(move |app| {
            match &mode {
                Mode::Launcher(_) => {
                    WebviewWindowBuilder::new(app, "splash", WebviewUrl::App("splash.html".into()))
                        .title(&title)
                        .inner_size(560.0, 320.0)
                        .resizable(false)
                        .decorations(false)
                        .center()
                        .build()?;
                    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                        .title(&title)
                        .inner_size(1120.0, 730.0)
                        .min_inner_size(1000.0, 660.0)
                        .decorations(false)
                        .center()
                        .visible(false)
                        .build()?;
                }
                Mode::Setup => {
                    WebviewWindowBuilder::new(app, "setup", WebviewUrl::App("setup.html".into()))
                        .title(format!("{title} — установка"))
                        .inner_size(880.0, 540.0)
                        .resizable(false)
                        .decorations(false)
                        .center()
                        .build()?;
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("ошибка запуска окна");
}

/// Папка игры рядом с exe, которую не ставил лаунчер (в ней нет `.launcher/install.json`):
/// мастер-копия владельца. Сначала папка с названием игры, потом любая другая с exe игры.
/// Не срабатывает, если игра стоит в папке самого лаунчера (обычная установка игрока).
fn master_copy_next_to(brand: &brand::Brand, exe_dir: &std::path::Path) -> Option<PathBuf> {
    let game_exe = &brand.renderers.first()?.exe;
    if exe_dir.join(game_exe).is_file() {
        return None;
    }
    let is_master = |d: &std::path::Path| d.join(game_exe).is_file() && !d.join(".launcher").join("install.json").exists();
    let named = exe_dir.join(&brand.product);
    if is_master(&named) {
        return Some(named);
    }
    let mut found: Vec<PathBuf> = std::fs::read_dir(exe_dir).ok()?.flatten().map(|e| e.path()).filter(|d| d.is_dir() && is_master(d)).collect();
    found.sort();
    found.into_iter().next()
}
