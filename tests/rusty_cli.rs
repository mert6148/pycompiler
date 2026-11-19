use std::fs;
use std::io::Write;
use std::process::{Command, Output, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

fn run_with_stdin(source: &str) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_rusty"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("Rusty client should start");
    child
        .stdin
        .take()
        .expect("client stdin should be available")
        .write_all(source.as_bytes())
        .expect("source should be sent to client");
    child.wait_with_output().expect("client should finish")
}

#[test]
fn compiles_source_from_standard_input() {
    let result = run_with_stdin("print 6 * 7;");
    assert!(result.status.success());
    assert_eq!(String::from_utf8_lossy(&result.stdout), "42\n");
}

#[test]
fn returns_compiler_diagnostics_with_a_failure_exit_code() {
    let result = run_with_stdin("print missing;");
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("1:7: undefined variable"));
}

#[test]
fn compiles_a_source_file() {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock should be after the Unix epoch")
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "pycompiler-cli-{}-{nonce}.rusty",
        std::process::id()
    ));
    fs::write(&path, "let answer = 40 + 2; print answer;")
        .expect("temporary source file should be written");

    let result = Command::new(env!("CARGO_BIN_EXE_rusty"))
        .arg(&path)
        .output()
        .expect("Rusty client should start");
    fs::remove_file(path).expect("temporary source file should be removed");

    assert!(result.status.success());
    assert_eq!(String::from_utf8_lossy(&result.stdout), "42\n");
}

#[test]
fn displays_help_without_reading_stdin() {
    let result = Command::new(env!("CARGO_BIN_EXE_rusty"))
        .arg("--help")
        .output()
        .expect("Rusty client should start");

    assert!(result.status.success());
    assert!(String::from_utf8_lossy(&result.stdout).contains("Usage:"));
}
