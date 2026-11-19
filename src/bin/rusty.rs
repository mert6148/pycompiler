use pycompiler::compiler::compile_and_run;
use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::path::PathBuf;
use std::process::ExitCode;

const USAGE: &str = "Rusty compiler client

Usage:
  rusty [FILE]
  rusty -
  rusty --help

If FILE is omitted, source is read from standard input. Use '-' to explicitly
read source from standard input.";

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("rusty: {message}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args_os().skip(1);
    let first = args.next();

    if matches!(first.as_deref(), Some(value) if value == "--help" || value == "-h") {
        if args.next().is_some() {
            return Err(format!("unexpected argument after --help\n\n{USAGE}"));
        }
        println!("{USAGE}");
        return Ok(());
    }

    if matches!(first.as_deref(), Some(value) if value == "--version" || value == "-V") {
        if args.next().is_some() {
            return Err("unexpected argument after --version".into());
        }
        println!("rusty {}", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }

    let source = match first {
        None => read_stdin().map_err(|error| format!("could not read standard input: {error}"))?,
        Some(path) if path == "-" => {
            if args.next().is_some() {
                return Err(format!("only one source file may be provided\n\n{USAGE}"));
            }
            read_stdin().map_err(|error| format!("could not read standard input: {error}"))?
        }
        Some(path) => {
            if args.next().is_some() {
                return Err(format!("only one source file may be provided\n\n{USAGE}"));
            }
            let path = PathBuf::from(path);
            fs::read_to_string(&path)
                .map_err(|error| format!("could not read '{}': {error}", path.display()))?
        }
    };

    let output = compile_and_run(&source).map_err(|error| error.to_string())?;
    io::stdout()
        .write_all(output.as_bytes())
        .map_err(|error| format!("could not write program output: {error}"))
}

fn read_stdin() -> io::Result<String> {
    let mut source = String::new();
    io::stdin().read_to_string(&mut source)?;
    Ok(source)
}
