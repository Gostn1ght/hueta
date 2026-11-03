fn main() {
    // brand.json общий с лаунчером: битый JSON должен ломать сборку.
    println!("cargo:rerun-if-changed=../../app/brand.json");
    let s = std::fs::read_to_string("../../app/brand.json").expect("нет app/brand.json");
    if let Err(e) = serde_json::from_str::<serde_json::Value>(&s) {
        panic!("brand.json: {e}");
    }
    tauri_build::build()
}
