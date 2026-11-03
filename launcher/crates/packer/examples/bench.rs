use std::io::Read;
use std::time::Instant;
fn main() {
    let p = std::env::args().nth(1).unwrap();
    let t = Instant::now();
    let mut d = Vec::new();
    std::fs::File::open(&p).unwrap().read_to_end(&mut d).unwrap();
    println!("read {} MB in {:?}", d.len() >> 20, t.elapsed());
    let t = Instant::now();
    let h = blake3::hash(&d);
    println!("blake3 {:?} {}", t.elapsed(), &h.to_hex()[..8]);
    let t = Instant::now();
    let n = fastcdc::v2020::FastCDC::new(&d, 256 << 10, 1 << 20, 4 << 20).count();
    println!("fastcdc mem {:?} chunks {n}", t.elapsed());
    let t = Instant::now();
    let n = fastcdc::v2020::StreamCDC::new(std::io::BufReader::with_capacity(4 << 20, std::fs::File::open(&p).unwrap()), 256 << 10, 1 << 20, 4 << 20).count();
    println!("streamcdc file {:?} chunks {n}", t.elapsed());
}
