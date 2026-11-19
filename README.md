# Rust IDE

Rust IDE is a small, local web IDE with a VS Code-inspired layout and a Rust
compiler for the included `Rusty` teaching language. It uses only the Rust
standard library.

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
Rust test suite, `npm run build` makes a release build, and
`npm run format:check` checks Rust formatting. Node.js is needed only for the
`npm` commands; the app itself uses Cargo and the Rust standard library.

Open [http://127.0.0.1:3030](http://127.0.0.1:3030). The server binds to
localhost only. Press **Run** or **Ctrl+Enter** to compile and execute the
editor contents. Source is saved in the browser's local storage.

## Rusty language

Statements end with a semicolon. Variables are declared with `let`; existing
variables can be reassigned. `print` writes an integer to the output panel.
The compiler supports integer arithmetic (`+`, `-`, `*`, `/`), comparisons
(`==`, `!=`, `<`, `<=`, `>`, `>=`), parentheses, unary minus, and `//` line
comments. Comparison results are `1` (true) or `0` (false); any nonzero value
is true in an `if` or `while` condition. Blocks use braces, and variables
declared inside a block are local to that block.

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
