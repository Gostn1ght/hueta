fn main() {
    // brand.json зашивается в exe: битый JSON должен ломать сборку, а не запуск у игрока.
    println!("cargo:rerun-if-changed=brand.json");
    let s = std::fs::read_to_string("brand.json").expect("нет brand.json");
    if let Err(e) = serde_json::from_str::<serde_json::Value>(&s) {
        panic!("brand.json: {e}");
    }
    tauri_build::build()
}
