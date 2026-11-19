# Rust IDE

Rust IDE is a small, local web IDE with a VS Code-inspired layout and a Rust
compiler for the included `Rusty` teaching language. The compiler and its
clients are written in Rust; the project uses SQLite for local code history.

The compiler implementation and its tests are in `src/compiler.rs`; `src/lib.rs`
exports the compiler API, and `src/main.rs` hosts the local web server.

## Documentation

See [docs/README.md](docs/README.md) for the architecture, compiler pipeline,
Rusty language syntax, and guidance for extending the compiler. Generate the
Rust API reference with `cargo doc --no-deps`; it is written to
`target/doc/pycompiler/index.html`.

## Run

Install Rust, then start the app from this directory:

```powershell
cargo run
```

On Windows, `run.bat` or `npm start` also starts the app. `npm test` runs the
Rust test suite, `npm run build` makes a release build, `npm run format:check`
checks Rust formatting, and `npm run compile -- example.rusty` runs a Rusty
source file with the command-line client. Node.js is needed only for the `npm`
commands. The compiler code is shared by the browser IDE and the `rusty`
command-line client.

Open [http://127.0.0.1:3030](http://127.0.0.1:3030). The server binds to
localhost only. Press **Run** or **Ctrl+Enter** to compile and execute the
editor contents. The redesigned editor highlights Rusty syntax, saves source
in the browser's local storage, and shows clickable diagnostics with line
numbers in the Problems panel. Each editor save is also versioned in the local
SQLite database; the **Sürümler** panel can restore earlier versions. Changed
Rust files under `src/` are snapshotted when the server starts.

The compiler can also be used directly from a terminal:

```powershell
cargo run --bin rusty -- examples\hello.rusty
Get-Content examples\hello.rusty | cargo run --bin rusty
```

The `rusty` client prints program output to standard output and reports
compiler or file errors to standard error with a nonzero exit code.

## Rusty language

Statements end with a semicolon. Variables are declared with `let`; existing
variables can be reassigned. `print` writes an integer to the output panel.
The compiler supports integer arithmetic (`+`, `-`, `*`, `/`, `%`), comparisons
(`==`, `!=`, `<`, `<=`, `>`, `>=`), parentheses, unary minus, and `//` line
comments. Logical `&&` and `||` operators short-circuit, unary `!` negates
truthiness, and `break` / `continue` control loops. Comparison results are
`1` (true) or `0` (false); any nonzero value is true in an `if` or `while`
condition. Blocks use braces, and variables declared inside a block are local
to that block.

```text
let total = 0;
let index = 1;
while index <= 5 {
    total = total + index;
    index = index + 1;
}

if total == 15 {
    print total;
} else {
    print 0;
}
```

Run the compiler tests with `cargo test`.
