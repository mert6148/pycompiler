# Rust IDE

Rust IDE is a small, local web IDE with a VS Code-inspired layout and a Rust
compiler for the included `Rusty` teaching language. It uses only the Rust
standard library.

## Run

Install Rust, then start the app from this directory:

```powershell
cargo run
```

Open [http://127.0.0.1:3030](http://127.0.0.1:3030). The server binds to
localhost only. Press **Run** or **Ctrl+Enter** to compile and execute the
editor contents. Source is saved in the browser's local storage.

## Rusty language

Statements end with a semicolon. Variables are declared with `let`; existing
variables can be reassigned. `print` writes an integer to the output panel.
The compiler supports integer arithmetic (`+`, `-`, `*`, `/`), parentheses,
unary minus, and `//` line comments.

```text
let base = 40;
let answer = base + 2;
print answer;
```

Run the compiler tests with `cargo test`.
