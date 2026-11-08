//! The source fingerprint compiled into the extension (`hsbg_engine.build_info()`): which sources
//! a loaded binary was built from. The card data does not change when the engine's code
//! does, so it cannot tell an old binary from a new one.
//!
//! FNV-1a (64 bit) over, for every `.rs` file of the two crates and the card data sorted by
//! path: the path relative to `crates/` with `/`, a zero byte, and the CRC-32 of the file
//! without carriage returns (4 bytes, little endian). `hsbg_engine.source_hash()` computes the
//! same in Python from a checkout.
//!
//! fork 差异：额外补上 macOS 上 PyO3 扩展模块需要的 `-undefined dynamic_lookup` 链接参数
//! （上游仓库靠 maturin 注入，纯 `cargo build --release` 在 macOS 会因 `_Py*` 未定义而失败；
//! 这里按 pyo3-build-config 的官方做法在 build.rs 里声明，使 `cargo build --release` 直接可用）。
use std::fs;
use std::path::{Path, PathBuf};

fn collect(dir: &Path, out: &mut Vec<PathBuf>) {
    let mut entries: Vec<PathBuf> = fs::read_dir(dir)
        .unwrap_or_else(|e| panic!("{}: {e}", dir.display()))
        .map(|e| e.unwrap().path())
        .collect();
    entries.sort();
    for p in entries {
        if p.is_dir() {
            collect(&p, out);
        } else if p.extension().is_some_and(|x| x == "rs") {
            out.push(p);
        }
    }
}

fn crc32(data: &[u8]) -> u32 {
    let mut crc = !0u32;
    for &b in data.iter().filter(|b| **b != b'\r') {
        crc ^= b as u32;
        for _ in 0..8 {
            crc = (crc >> 1) ^ (0xEDB8_8320 & (!(crc & 1)).wrapping_add(1));
        }
    }
    !crc
}

fn main() {
    // fork：macOS 上 PyO3 扩展模块（cdylib）不链接 libpython，需要允许未定义符号在加载时
    // 由解释器解析；maturin 会自己注入这两个参数，纯 cargo 构建则必须在这里声明。
    // 其它平台无需处理（Linux 共享库默认允许未定义符号；Windows 用 maturin 构建）。
    #[cfg(target_os = "macos")]
    {
        println!("cargo:rustc-cdylib-link-arg=-undefined");
        println!("cargo:rustc-cdylib-link-arg=dynamic_lookup");
    }

    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let crates = manifest.parent().unwrap().to_path_buf();
    let mut files = vec![];
    collect(&crates.join("hsbg-engine").join("src"), &mut files);
    collect(&crates.join("hsbg-engine-py").join("src"), &mut files);
    files.push(crates.join("hsbg-engine").join("data").join("cards.json"));
    let mut named: Vec<(String, PathBuf)> = files
        .into_iter()
        .map(|f| {
            let rel = f.strip_prefix(&crates).unwrap();
            let rel: Vec<String> = rel
                .components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect();
            (rel.join("/"), f)
        })
        .collect();
    named.sort();
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    let mut eat = |b: u8| {
        h ^= b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    };
    for (rel, f) in &named {
        rel.bytes().for_each(&mut eat);
        eat(0);
        crc32(&fs::read(f).unwrap())
            .to_le_bytes()
            .into_iter()
            .for_each(&mut eat);
    }
    println!("cargo:rustc-env=HSBG_ENGINE_SOURCE_HASH={h:016x}");
    println!(
        "cargo:rustc-env=HSBG_ENGINE_PROFILE={}",
        std::env::var("PROFILE").unwrap_or_default()
    );
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=src");
    println!("cargo:rerun-if-changed=../hsbg-engine/src");
    println!("cargo:rerun-if-changed=../hsbg-engine/data/cards.json");
}
