//! Что никогда не раздаётся игрокам: файлы выделенного сервера, серверные архивы и скрипты,
//! ключи, личные данные. Список зашит в код — его нельзя выключить настройкой или флагом.
//! Используется упаковщиком (такие файлы не попадают в релиз) и раздачей у игроков.

const DENY: &[&str] = &[
    // выделенный сервер и его окружение
    "dedicated/**",
    "server/**",
    "hoster/**",
    "fsgame_server*",
    "resources/95_server*",
    "resources/*_server.db*",
    "**/*_server.db?",
    "Start Server Panel.cmd",
    "Start Locations.cmd",
    "Admin Rights.cmd",
    "README-server-addon.txt",
    // ключи, рабочие папки владельца, личные данные игроков
    "Compressor/**",
    "**/private/**",
    "**/*.key",
    "**/*.secret",
    "**/*.pdb",
    "appdata/**",
    "gamedata/**",
    "fsgame.ltx",
    ".launcher/**",
    "**/*.nwpart",
    "**/*.log",
];

fn set() -> &'static globset::GlobSet {
    static SET: std::sync::OnceLock<globset::GlobSet> = std::sync::OnceLock::new();
    SET.get_or_init(|| {
        let mut b = globset::GlobSetBuilder::new();
        for p in DENY {
            b.add(globset::GlobBuilder::new(p).case_insensitive(true).literal_separator(false).build().expect("deny glob"));
        }
        b.build().expect("deny set")
    })
}

/// true — файл нельзя упаковывать в релиз и отдавать другим игрокам.
pub fn is_never_distributed(path: &str) -> bool {
    let p = path.replace('\\', "/");
    set().is_match(&p)
}

#[cfg(test)]
mod tests {
    use super::is_never_distributed as deny;
    #[test]
    fn server_files_are_denied() {
        for p in [
            "dedicated/LostZoneServerDX11.exe",
            "server/scripts/x.script",
            "hoster/netcoop_cluster_panel.ps1",
            "resources/95_server_lostzone_lz_scripts_000.db0",
            "resources/99_lz_patch_000001_server.db0",
            "fsgame_server.ltx",
            "Start Locations.cmd",
            "appdata/server/accounts.json",
            "Compressor/private/lzpack-v1.key",
        ] {
            assert!(deny(p), "{p}");
        }
        for p in ["bin/LostZoneClientDX11.exe", "resources/90_lostzone_lz_misc.db0", "resources/99_lz_patch_000002.db0", "client/configs/system.ltx", "fsgame.template"] {
            assert!(!deny(p), "{p}");
        }
    }
}
