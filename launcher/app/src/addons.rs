//! Built-in menu packages. Selection is one atomic file read by the game; base
//! archives are never overwritten or removed. Future packages extend this catalog.
use serde::Serialize;
use std::path::Path;

pub const MIN_PATCH: u32 = 63;
const THEMES: &[(&str, &str, &str, bool)] = &[
    ("room", "Комната — 3D", "Интерактивные предметы, персонаж и радио. Требуется DirectX 11.", true),
    ("campfire", "Костёр — 2D", "Готовое анимированное меню Anomaly: костёр в ангаре. Без радио и фоновой музыки.", true),
    ("night", "Ночное убежище — 2D", "Готовое анимированное меню Anomaly: убежище при свече, меню слева. Без фоновой музыки.", true),
];

#[derive(Serialize)]
pub struct Addon {
    id: &'static str,
    name: &'static str,
    description: &'static str,
    installed: bool,
    available: bool,
    conflicts: Vec<&'static str>,
    conflict_names: Vec<&'static str>,
    requires: String,
}

pub fn selected(dir: &Path) -> String {
    let value = std::fs::read_to_string(dir.join("appdata/player/netcoop_menu_theme.txt")).unwrap_or_default();
    let value = value.trim();
    if THEMES.iter().any(|t| t.0 == value && t.3) { value.into() } else { "classic".into() }
}

pub fn patch(dir: &Path) -> u32 {
    std::fs::read(dir.join("runtime-layout.json")).ok()
        .and_then(|b| serde_json::from_slice::<serde_json::Value>(&b).ok())
        .and_then(|v| v.get("patch")?.as_str()?.parse().ok()).unwrap_or(0)
}

pub fn supports_room(executable: &str) -> bool {
    executable.replace('\\', "/").rsplit('/').next().unwrap_or("").eq_ignore_ascii_case("LostZoneClientDX11.exe")
}

pub fn list(dir: &Path, room_supported: bool) -> Vec<Addon> {
    let current = selected(dir);
    let compatible = patch(dir) >= MIN_PATCH;
    THEMES.iter().map(|&(id, name, description, ready)| Addon {
        id, name, description, installed: current == id, available: compatible && ready && (id != "room" || room_supported),
        conflicts: THEMES.iter().filter(|t| t.0 != id).map(|t| t.0).collect(),
        conflict_names: THEMES.iter().filter(|t| t.0 != id).map(|t| t.1).collect(),
        requires: if !ready { "В разработке".into() }
            else if !compatible { format!("Нужно обновление игры: данные {MIN_PATCH:06} или новее") }
            else if id == "room" && !room_supported { "Несовместимо с DX8 / R1. Выберите DirectX 11. В DX8 игра откроет обычное 2D-меню.".into() }
            else { "После перезапуска игры. Удаление возвращает обычное 2D-меню без музыки.".into() },
    }).collect()
}

fn resolve(current: &str, id: &str, install: bool, replace_conflicts: bool, game_patch: u32) -> Result<String, String> {
    let theme = THEMES.iter().find(|t| t.0 == id).ok_or("Неизвестный аддон")?;
    if !install {
        return if current == id { Ok("classic".into()) } else { Err("Этот аддон не установлен".into()) };
    }
    if !theme.3 { return Err("Этот аддон ещё готовится".into()); }
    if game_patch < MIN_PATCH { return Err("Сначала обновите игру для поддержки аддонов меню".into()); }
    if current != "classic" && current != id && !replace_conflicts {
        return Err("Конфликт с установленным меню. Используйте «Заменить меню».".into());
    }
    Ok(id.into())
}

pub fn change(dir: &Path, id: &str, install: bool, replace_conflicts: bool, room_supported: bool) -> Result<(), String> {
    if install && id == "room" && !room_supported { return Err("3D-комната требует DirectX 11. Сначала переключите рендер.".into()); }
    let next = resolve(&selected(dir), id, install, replace_conflicts, patch(dir))?;
    let path = dir.join("appdata/player/netcoop_menu_theme.txt");
    std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
    let temporary = path.with_extension("txt.new");
    let file = std::fs::File::create(&temporary).map_err(|e| e.to_string())?;
    use std::io::Write;
    (&file).write_all(format!("{next}\n").as_bytes()).and_then(|_| file.sync_all()).map_err(|e| e.to_string())?;
    drop(file);
    // MoveFileEx replaces one existing selector on Windows without a remove /
    // rename gap. A failed commit leaves the previous selected package intact.
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH};
    let wide = |p: &Path| p.as_os_str().encode_wide().chain(Some(0)).collect::<Vec<_>>();
    let ok = unsafe { MoveFileExW(wide(&temporary).as_ptr(), wide(&path).as_ptr(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) };
    if ok == 0 { return Err(std::io::Error::last_os_error().to_string()); }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn conflicts_require_explicit_replacement_and_uninstall_restores_default() {
        assert!(resolve("night", "room", true, false, MIN_PATCH).is_err());
        assert_eq!(resolve("night", "room", true, true, MIN_PATCH).unwrap(), "room");
        assert_eq!(resolve("room", "room", false, false, 0).unwrap(), "classic");
        assert!(resolve("classic", "room", true, false, 61).is_err());
        assert_eq!(resolve("classic", "night", true, false, MIN_PATCH).unwrap(), "night");
        assert!(resolve("classic", "../../anything", true, true, MIN_PATCH).is_err());
        assert!(supports_room("bin/LostZoneClientDX11.exe"));
        assert!(supports_room("bin\\LostZoneClientDX11.exe"));
        assert!(!supports_room("bin/LostZoneClientDX8.exe"));
        assert!(change(Path::new("unused"), "room", true, true, false).is_err());
    }
}
