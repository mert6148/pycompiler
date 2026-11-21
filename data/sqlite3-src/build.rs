use std::env;
use std::path::PathBuf;

const SQLITE_SOURCE: &str = "source/sqlite3.c";
const SQLITE_HEADER: &str = "source/sqlite3.h";

fn main() {
    println!("cargo:rerun-if-changed={SQLITE_SOURCE}");
    println!("cargo:rerun-if-changed={SQLITE_HEADER}");
    println!("cargo:rerun-if-env-changed=WASI_SDK_PATH");
    println!("cargo:rerun-if-env-changed=WASI_TARGET_ENV");
    println!("cargo:rerun-if-env-changed=CARGO_CFG_SQLITE3_SRC_WASI_SDK_PATH");
    println!("cargo:rerun-if-env-changed=CARGO_CFG_SQLITE3_SRC_WASI_TARGET_ENV");
    println!("cargo:rerun-if-env-changed=SQLITE3_SRC_WASI_SDK_PATH");
    println!("cargo:rerun-if-env-changed=SQLITE3_SRC_WASI_TARGET_ENV");

    if let Err(error) = try_main() {
        panic!("failed to configure SQLite: {error}");
    }
}

fn try_main() -> Result<(), Box<dyn std::error::Error>> {
    let bundled = env::var_os("CARGO_FEATURE_BUNDLED").is_some();
    let system = env::var_os("CARGO_FEATURE_SYSTEM").is_some();

    if bundled && system {
        return Err("the 'bundled' and 'system' features are mutually exclusive".into());
    }

    if bundled {
        build_bundled()?;
        return Ok(());
    }

    if system {
        pkg_config::Config::new()
            .cargo_metadata(true)
            .probe("sqlite3")
            .map_err(|error| {
                format!("the 'system' feature requires an installed SQLite development library: {error}")
            })?;
        return Ok(());
    }

    if pkg_config::Config::new()
        .cargo_metadata(true)
        .probe("sqlite3")
        .is_ok()
    {
        return Ok(());
    }

    build_bundled()
}

fn build_bundled() -> Result<(), Box<dyn std::error::Error>> {
    let manifest_dir = PathBuf::from(
        env::var_os("CARGO_MANIFEST_DIR").ok_or("Cargo did not provide CARGO_MANIFEST_DIR")?,
    );
    let source = manifest_dir.join(SQLITE_SOURCE);
    if !source.is_file() {
        return Err(format!("SQLite amalgamation was not found at {}", source.display()).into());
    }

    let mut build = cc::Build::new();
    build.file(source);

    for (name, value) in env::vars() {
        if name.starts_with("SQLITE_") {
            println!("cargo:rerun-if-env-changed={name}");
            build.define(&name, Some(value.as_str()));
        }
    }

    let target_family = env::var("CARGO_CFG_TARGET_FAMILY").unwrap_or_default();
    if target_family.split(',').any(|family| family == "wasm") {
        configure_wasi(&mut build)?;
    }

    build.compile("sqlite3");
    Ok(())
}

fn configure_wasi(build: &mut cc::Build) -> Result<(), Box<dyn std::error::Error>> {
    let sdk_path = env::var_os("CARGO_CFG_SQLITE3_SRC_WASI_SDK_PATH")
        .or_else(|| env::var_os("SQLITE3_SRC_WASI_SDK_PATH"))
        .or_else(|| env::var_os("WASI_SDK_PATH"))
        .ok_or("set SQLITE3_SRC_WASI_SDK_PATH or WASI_SDK_PATH to the WASI SDK")?;
    let sdk_path = PathBuf::from(sdk_path).canonicalize()?;
    let clang = sdk_path
        .join("bin")
        .join(if cfg!(windows) { "clang.exe" } else { "clang" });
    if !clang.is_file() {
        return Err(format!("WASI clang was not found at {}", clang.display()).into());
    }

    build.compiler(clang);
    build.define("__wasi__", None);
    build.define("SQLITE_OMIT_LOAD_EXTENSION", None);
    build.define("SQLITE_THREADSAFE", Some("0"));
    build.flag_if_supported("-Wno-unused");
    build.flag_if_supported("-Wno-unused-parameter");

    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_os != "wasi" {
        let target_env = env::var("CARGO_CFG_SQLITE3_SRC_WASI_TARGET_ENV")
            .or_else(|_| env::var("SQLITE3_SRC_WASI_TARGET_ENV"))
            .or_else(|_| env::var("WASI_TARGET_ENV"))
            .map_err(|_| {
                "set SQLITE3_SRC_WASI_TARGET_ENV or WASI_TARGET_ENV when targeting non-WASI wasm"
            })?;
        build.target(&format!("wasm32-wasi{target_env}"));
    }

    Ok(())
}
