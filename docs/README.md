# Rust IDE and Rusty compiler

This guide describes how the project is organized, how Rusty source is
compiled, and how to extend the language safely.

## Run and test

Install the Rust toolchain, then run the IDE from the project root:

```powershell
cargo run
```

Open <http://127.0.0.1:3030>. On Windows, `run.bat` is an alternative launcher.
The `package.json` scripts also provide `npm start`, `npm test`,
`npm run build`, and `npm run format:check`.

Run the compiler and documentation tests with:

```powershell
cargo test
```

Generate the API documentation with:

```powershell
cargo doc --no-deps
```

Open `target/doc/pycompiler/index.html` to browse the generated Rust
documentation. The crate-level page is sourced from this file, so the project
overview is also available alongside the compiler API.

## Project layout

| Path | Responsibility |
| --- | --- |
| `src/lib.rs` | Exports the compiler module and includes this guide as the crate-level Rust documentation. |
| `src/main.rs` | Starts the localhost HTTP server, serves the IDE assets, and forwards `/api/run` requests to the compiler library. |
| `src/bin/rusty.rs` | Command-line client that runs a Rusty file or source from standard input. |
| `src/compiler.rs` | Implements the Rusty lexer, AST parser, scoped interpreter, and compiler tests. |
| `src/database.rs` | Creates SQLite code history, stores editor versions, and snapshots changed Rust source files. |
| `web/index.html` | IDE structure: file explorer, editor, output panel, and status bar. |
| `web/style.css` | VS Code-inspired layout and colors. |
| `web/app.js` | Editor behavior, local saving, SQLite autosave, version history, and compiler API requests. |
| `run.bat` | Windows launcher that checks for Cargo and runs the app. |
| `Cargo.toml` | Rust package configuration. |
| `Dockerfile` | Multi-stage release build and non-root runtime image. |
| `docker-compose.yml` | Local container configuration with a persistent SQLite volume. |
| `.dockerignore` | Keeps secrets, local databases, and build artifacts out of image build context. |

## Request-to-output flow

1. On startup, `main.rs` snapshots changed `.rs` files under `src/` into
   `data/code-history.sqlite3`.
2. The browser keeps an immediate local copy and sends debounced saves to
   `POST /api/save`. SQLite stores each changed version of `main.rusty`;
   identical consecutive contents are deduplicated.
3. The **Sürümler** panel loads the latest versions from `GET /api/versions`.
   **Geri yükle** retrieves an editor version through `POST /api/restore`;
   restoring a version is itself saved as a new version.
4. The browser sends the editor contents as UTF-8 text to `POST /api/run`.
5. `main.rs` validates the request body and calls
   `compiler::compile_and_run`.
6. The lexer converts characters to tokens and records line/column positions.
7. The parser validates statements and variable declarations, then builds an
   AST. Lexical scope is represented by nested declaration maps.
8. The AST interpreter executes statements and expressions, performs short-
   circuit evaluation, collects `print` output, and applies checked arithmetic.
   Execution stops after one million interpreter steps.
9. The server returns the output as plain text, or a diagnostic with HTTP 400.

The `rusty` command-line client uses the same `compiler::compile_and_run`
function. Give it a `.rusty` file or pipe source through standard input:

```powershell
cargo run --bin rusty -- examples\hello.rusty
Get-Content examples\hello.rusty | cargo run --bin rusty
```

The runnable sample is `examples/hello.rusty`.

Compiler diagnostics are printed to standard error and cause a nonzero exit
code. The command-line client tests are in `tests/rusty_cli.rs`.

The SQLite database is local and is excluded from Git by `.gitignore`. Versions
are stored as plain text in the database; this provides history and recovery,
not encryption. Keep a separate backup of the database if protection against
disk loss is required.

## Docker deployment

Build and run with Docker Compose:

```powershell
docker compose up --build
```

Compose publishes port `3030` and mounts `pycompiler-data` at `/app/data`,
keeping `code-history.sqlite3` across container restarts and rebuilds.
`docker compose down` stops and removes the container without removing the
volume; `docker compose down --volumes` also deletes the stored code history.

The image is built in a Rust stage and runs in a minimal Debian stage as an
unprivileged user. The root filesystem is read-only, Linux capabilities are
dropped, and `/tmp` is ephemeral. The SQLite volume is the writable persistent
path. Container builds exclude `.env` files, local databases, and Cargo build
outputs.

The executable defaults to binding `127.0.0.1:3030` for local runs. Docker
sets `RUSTY_BIND_ADDRESS=0.0.0.0:3030` for port forwarding and
`RUSTY_DATA_DIR=/app/data` for persistent database storage.

Useful local endpoints:

| Method and path | Purpose |
| --- | --- |
| `POST /api/save` | Save an editor source version. |
| `GET /api/versions` | List recent `main.rusty` versions. |
| `POST /api/restore` | Load an editor version by its numeric ID. |
| `POST /api/run` | Compile and run Rusty source. |

The public compiler entry point and `CompileError` are documented in the
generated API reference under the `compiler` module. Their implementation is
in `src/compiler.rs`.

## Rusty language

Rusty is an integer-only teaching language. Statements end with semicolons;
blocks use braces.

```text
// Add the numbers from one through five.
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

Supported statements:

```text
let name = expression;
name = expression;
print expression;
if expression { statements } else { statements }
while expression { statements }
break;
continue;
```

Variables must be declared before use. A variable declared inside a block is
local to that block; assignments to variables declared by an outer block are
allowed. Conditions treat zero as false and every nonzero integer as true.
Comparisons evaluate to `1` or `0`. `&&` and `||` evaluate operands with short-
circuit behavior; `!` converts a value to `0` or `1`.

Operator precedence, from highest to lowest:

| Operators | Meaning |
| --- | --- |
| unary `-` | Negation |
| `*`, `/`, `%` | Multiplication, division, remainder |
| `+`, `-` | Addition, subtraction |
| `==`, `!=`, `<`, `<=`, `>`, `>=` | Integer comparisons |

Parentheses can be used to group expressions. `//` starts a line comment.

## Compiler implementation notes

- `TokenKind` and `Token` represent lexical units and their source positions.
- `lex` scans digits, identifiers, keywords, punctuation, and comments.
- `Parser::statement` handles declarations, assignments, printing, conditionals,
  loops, and scoped blocks.
- `Parser::expression` uses precedence climbing and emits postfix operations.
- `Instruction` is the compiler's stack-machine bytecode.
- `execute` maintains the operand stack and variable store, applies checked
  arithmetic, and interprets jump instructions.
- The unit tests in `compiler.rs` cover precedence, scope, diagnostics,
  comparisons, control flow, and execution limits.

When adding an operator, update the token type and lexer, define its precedence
and bytecode in the parser, implement its VM behavior, and add a focused test.
