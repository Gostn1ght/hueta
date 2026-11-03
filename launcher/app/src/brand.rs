//! Брендинг и настройки сборки: зашиты в exe из `brand.json`.

use serde::{Deserialize, Serialize};

#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct Renderer {
    pub name: String,
    pub hint: String,
    pub exe: String,
    pub args: String,
}

#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct Links {
    pub bug: String,
    pub discord: String,
    pub youtube: String,
}

#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct Brand {
    pub product: String,
    pub title: String,
    pub publisher: String,
    pub exe_name: String,
    pub default_install_dir: String,
    pub base_urls: Vec<String>,
    pub public_key: String,
    pub news_url: String,
    pub links: Links,
    pub renderers: Vec<Renderer>,
    pub game_working_dir: String,
    /// Шаблон аргументов подключения: {ip} {port} {login} {password}. Пусто — не передаём.
    pub connect_args: String,
    pub connections: usize,
    pub max_retries: u32,
    pub keep: Vec<String>,
    pub clean_on_update: Vec<String>,
    pub minimize_on_start: bool,
    pub auto_update: bool,
    pub setup_text: String,
    /// Раздавать установленную игру другим игрокам (P2P), если игрок не выключил.
    #[serde(default = "yes")]
    pub p2p_seed_default: bool,
    /// Только через relay: игроки не видят IP друг друга и сервера.
    #[serde(default = "yes")]
    pub p2p_hide_ip: bool,
    /// relay-серверы P2P; пусто — список по умолчанию.
    #[serde(default = "gamesync::p2p::default_relays")]
    pub p2p_relays: Vec<String>,
    /// Файлы игрока (настройки, которые меняет игра): ставятся, если нет, но не перезаписываются.
    #[serde(default)]
    pub user_files: Vec<String>,
    /// Перед запуском: собрать файл из шаблона, подставив {ROOT} — путь к папке игры.
    #[serde(default)]
    pub launch_template: Option<LaunchTemplate>,
    /// Перед запуском: создать эти папки.
    #[serde(default)]
    pub launch_mkdirs: Vec<String>,
    /// Если этот файл есть — игру не запускать (идёт обновление).
    #[serde(default)]
    pub launch_block_file: String,
}

#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct LaunchTemplate {
    pub from: String,
    pub to: String,
}

fn yes() -> bool {
    true
}

pub fn load() -> Brand {
    serde_json::from_str(include_str!("../brand.json")).expect("brand.json повреждён")
}
