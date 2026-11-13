"""A small compiler for an educational, block-structured language.

Example:
    let count = 3
    while count > 0 {
        print(count)
        count = count - 1
    }

Run ``python compiler.py program.pc`` to emit Python, or add ``--run`` to
execute the compiled program. Run ``python compiler.py --ide`` to launch the
local browser-based editor.
"""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence
from urllib.parse import parse_qs, urlsplit
import webbrowser


class CompileError(Exception):
    """A source error with a one-based line and column."""

    def __init__(self, message: str, line: int, column: int) -> None:
        self.message = message
        self.line = line
        self.column = column
        super().__init__(f"{line}:{column}: {message}")


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    column: int


_TOKEN_PATTERN = re.compile(
    r"""
    (?P<SPACE>[ \t\r]+)
    |(?P<COMMENT>\#[^\n]*)
    |(?P<NUMBER>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
    |(?P<STRING>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
    |(?P<IDENT>[A-Za-z_]\w*)
    |(?P<OP>\*\*|//|==|!=|<=|>=|&&|\|\||[+\-*/%<>=!])
    |(?P<PUNCT>[(){};,])
    |(?P<NEWLINE>\n)
    """,
    re.VERBOSE,
)


def tokenize(source: str) -> list[Token]:
    """Convert source text into tokens, retaining locations for diagnostics."""
    tokens: list[Token] = []
    line = 1
    column = 1
    position = 0

    while position < len(source):
        match = _TOKEN_PATTERN.match(source, position)
        if match is None:
            raise CompileError(
                f"unexpected character {source[position]!r}", line, column
            )

        value = match.group()
        kind = match.lastgroup
        if kind == "NEWLINE":
            tokens.append(Token(kind, value, line, column))
            line += 1
            column = 1
        else:
            if kind == "PUNCT" and value == ";":
                tokens.append(Token("NEWLINE", value, line, column))
            elif kind not in {"SPACE", "COMMENT"}:
                tokens.append(Token(kind or "", value, line, column))
            column += len(value)
        position = match.end()

    tokens.append(Token("EOF", "", line, column))
    return tokens


class Expression:
    pass


@dataclass(frozen=True)
class Literal(Expression):
    value: int | float | str | bool


@dataclass(frozen=True)
class Variable(Expression):
    name: str


@dataclass(frozen=True)
class Unary(Expression):
    operator: str
    operand: Expression


@dataclass(frozen=True)
class Binary(Expression):
    left: Expression
    operator: str
    right: Expression


class Statement:
    pass


@dataclass(frozen=True)
class Assignment(Statement):
    name: str
    value: Expression


@dataclass(frozen=True)
class Print(Statement):
    values: list[Expression]


@dataclass(frozen=True)
class If(Statement):
    condition: Expression
    body: list[Statement]
    else_body: list[Statement]


@dataclass(frozen=True)
class While(Statement):
    condition: Expression
    body: list[Statement]


class Parser:
    def __init__(self, tokens: Sequence[Token]) -> None:
        self.tokens = tokens
        self.position = 0

    def parse(self) -> list[Statement]:
        statements: list[Statement] = []
        self._skip_newlines()
        while not self._at("EOF"):
            statements.append(self._statement())
            self._skip_newlines()
        return statements

    def _statement(self) -> Statement:
        if self._is_word("let"):
            self._advance()
            name = self._expect_identifier("expected a variable name after 'let'")
            self._expect_value("=", "expected '=' after the variable name")
            statement: Statement = Assignment(name.value, self._expression())
            self._finish_simple_statement()
            return statement

        if self._is_word("print"):
            self._advance()
            if self._match_value("("):
                values: list[Expression] = []
                if not self._check_value(")"):
                    values.append(self._expression())
                    while self._match_value(","):
                        values.append(self._expression())
                self._expect_value(")", "expected ')' after the printed value")
            else:
                values = [self._expression()]
            statement = Print(values)
            self._finish_simple_statement()
            return statement

        if self._is_word("if"):
            self._advance()
            condition = self._expression()
            body = self._block()
            self._skip_newlines()
            else_body: list[Statement] = []
            if self._match_word("else"):
                else_body = self._block()
            return If(condition, body, else_body)

        if self._is_word("while"):
            self._advance()
            condition = self._expression()
            body = self._block()
            return While(condition, body)

        if self._at("IDENT") and self._peek().kind == "IDENT":
            name = self._expect_identifier("expected a variable name")
            self._expect_value("=", "expected '=' after the variable name")
            statement = Assignment(name.value, self._expression())
            self._finish_simple_statement()
            return statement

        self._error("expected an assignment, print, if, or while statement")

    def _block(self) -> list[Statement]:
        self._expect_value("{", "expected '{' before the block")
        statements: list[Statement] = []
        self._skip_newlines()
        while not self._at("EOF") and not self._check_value("}"):
            statements.append(self._statement())
            self._skip_newlines()
        self._expect_value("}", "expected '}' to close the block")
        return statements

    def _finish_simple_statement(self) -> None:
        if not self._at("NEWLINE") and not self._check_value("}") and not self._at("EOF"):
            self._error("expected the end of the statement")
        self._skip_newlines()

    def _expression(self) -> Expression:
        return self._or()

    def _or(self) -> Expression:
        expression = self._and()
        while self._match_word("or") or self._match_value("||"):
            operator = "or"
            expression = Binary(expression, operator, self._and())
        return expression

    def _and(self) -> Expression:
        expression = self._not()
        while self._match_word("and") or self._match_value("&&"):
            expression = Binary(expression, "and", self._not())
        return expression

    def _not(self) -> Expression:
        if self._match_word("not"):
            return Unary("not", self._not())
        return self._equality()

    def _equality(self) -> Expression:
        expression = self._comparison()
        while self._match_value("==") or self._match_value("!="):
            operator = self._previous().value
            expression = Binary(expression, operator, self._comparison())
        return expression

    def _comparison(self) -> Expression:
        expression = self._term()
        while (
            self._match_value("<")
            or self._match_value("<=")
            or self._match_value(">")
            or self._match_value(">=")
        ):
            operator = self._previous().value
            expression = Binary(expression, operator, self._term())
        return expression

    def _term(self) -> Expression:
        expression = self._factor()
        while self._match_value("+") or self._match_value("-"):
            operator = self._previous().value
            expression = Binary(expression, operator, self._factor())
        return expression

    def _factor(self) -> Expression:
        expression = self._unary()
        while (
            self._match_value("*")
            or self._match_value("/")
            or self._match_value("//")
            or self._match_value("%")
        ):
            operator = self._previous().value
            expression = Binary(expression, operator, self._unary())
        return expression

    def _unary(self) -> Expression:
        if self._match_value("!") or self._match_value("+") or self._match_value("-"):
            operator = self._previous().value
            return Unary("not" if operator == "!" else operator, self._unary())
        return self._power()

    def _power(self) -> Expression:
        expression = self._primary()
        if self._match_value("**"):
            expression = Binary(expression, "**", self._unary())
        return expression

    def _primary(self) -> Expression:
        if self._match("NUMBER"):
            token = self._previous()
            value: int | float
            if "." in token.value or "e" in token.value.lower():
                value = float(token.value)
            else:
                value = int(token.value)
            return Literal(value)

        if self._match("STRING"):
            token = self._previous()
            try:
                value = ast.literal_eval(token.value)
            except (SyntaxError, ValueError) as error:
                raise CompileError("invalid string literal", token.line, token.column) from error
            return Literal(value)

        if self._match("IDENT"):
            token = self._previous()
            if token.value == "true":
                return Literal(True)
            if token.value == "false":
                return Literal(False)
            if token.value in {"let", "print", "if", "else", "while", "and", "or", "not"}:
                self._error_at(token, f"'{token.value}' cannot be used as a value")
            return Variable(token.value)

        if self._match_value("("):
            expression = self._expression()
            self._expect_value(")", "expected ')' after the expression")
            return expression

        self._error("expected an expression")

    def _expect_identifier(self, message: str) -> Token:
        token = self._expect("IDENT", message)
        if token.value in {
            "let",
            "print",
            "if",
            "else",
            "while",
            "true",
            "false",
            "and",
            "or",
            "not",
        } or keyword.iskeyword(token.value) or token.value in {"True", "False", "None"}:
            self._error_at(token, f"'{token.value}' is reserved and cannot be a variable name")
        return token

    def _skip_newlines(self) -> None:
        while self._match("NEWLINE"):
            pass

    def _is_word(self, value: str) -> bool:
        return self._at("IDENT") and self._peek().value == value

    def _match_word(self, value: str) -> bool:
        if self._is_word(value):
            self._advance()
            return True
        return False

    def _match_value(self, value: str) -> bool:
        if self._peek().value == value:
            self._advance()
            return True
        return False

    def _expect_value(self, value: str, message: str) -> Token:
        if self._peek().value == value:
            return self._advance()
        self._error(message)

    def _match(self, kind: str) -> bool:
        if self._at(kind):
            self._advance()
            return True
        return False

    def _expect(self, kind: str, message: str) -> Token:
        if self._at(kind):
            return self._advance()
        self._error(message)

    def _at(self, kind: str) -> bool:
        return self._peek().kind == kind

    def _check_value(self, value: str) -> bool:
        return self._peek().value == value

    def _advance(self) -> Token:
        token = self._peek()
        if token.kind != "EOF":
            self.position += 1
        return token

    def _peek(self) -> Token:
        return self.tokens[self.position]

    def _previous(self) -> Token:
        return self.tokens[self.position - 1]

    def _error(self, message: str) -> None:
        token = self._peek()
        self._error_at(token, message)

    @staticmethod
    def _error_at(token: Token, message: str) -> None:
        raise CompileError(message, token.line, token.column)


def _render_expression(expression: Expression) -> str:
    if isinstance(expression, Literal):
        return repr(expression.value)
    if isinstance(expression, Variable):
        return expression.name
    if isinstance(expression, Unary):
        separator = " " if expression.operator == "not" else ""
        return f"({expression.operator}{separator}{_render_expression(expression.operand)})"
    if isinstance(expression, Binary):
        return (
            f"({_render_expression(expression.left)} {expression.operator} "
            f"{_render_expression(expression.right)})"
        )
    raise TypeError(f"unsupported expression: {type(expression).__name__}")


def _render_statements(statements: Sequence[Statement], indentation: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = "    " * indentation
    for statement in statements:
        if isinstance(statement, Assignment):
            lines.append(f"{prefix}{statement.name} = {_render_expression(statement.value)}")
        elif isinstance(statement, Print):
            values = ", ".join(_render_expression(value) for value in statement.values)
            lines.append(f"{prefix}print({values})")
        elif isinstance(statement, If):
            lines.append(f"{prefix}if {_render_expression(statement.condition)}:")
            lines.extend(_render_statements(statement.body, indentation + 1) or [prefix + "    pass"])
            if statement.else_body:
                lines.append(f"{prefix}else:")
                lines.extend(
                    _render_statements(statement.else_body, indentation + 1)
                    or [prefix + "    pass"]
                )
        elif isinstance(statement, While):
            lines.append(f"{prefix}while {_render_expression(statement.condition)}:")
            lines.extend(_render_statements(statement.body, indentation + 1) or [prefix + "    pass"])
        else:
            raise TypeError(f"unsupported statement: {type(statement).__name__}")
    return lines


def compile_source(source: str) -> str:
    """Compile source text into Python code."""
    statements = Parser(tokenize(source)).parse()
    lines = _render_statements(statements)
    return "\n".join(lines) + ("\n" if lines else "")


def run_source(source: str) -> None:
    """Compile and execute source with only ``print`` available as a builtin."""
    python_source = compile_source(source)
    exec(compile(python_source, "<source>", "exec"), {"__builtins__": {"print": print}})


def run_interactive() -> None:
    """Run source snippets interactively while preserving variables between them."""
    namespace: dict[str, object] = {"__builtins__": {"print": print}}
    source_lines: list[str] = []
    brace_depth = 0

    def execute_source(source: str) -> None:
        try:
            python_source = compile_source(source)
            exec(compile(python_source, "<interactive>", "exec"), namespace)
        except CompileError as error:
            print(error, file=sys.stderr)
        except Exception as error:
            print(f"runtime error: {error}", file=sys.stderr)

    while True:
        try:
            line = input("... " if brace_depth else ">>> ")
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            return

        if not source_lines and line.strip() in {":quit", ":exit"}:
            return
        if not source_lines and line.strip() == ":help":
            print("Enter a statement or block. Use :quit or :exit to leave.")
            continue
        if not line.strip() and not source_lines:
            continue

        source_lines.append(line)
        source = "\n".join(source_lines) + "\n"
        try:
            tokens = tokenize(source)
        except CompileError as error:
            print(error, file=sys.stderr)
            source_lines.clear()
            brace_depth = 0
            continue

        brace_depth = sum(
            1 if token.value == "{" else -1 if token.value == "}" else 0
            for token in tokens
            if token.kind == "PUNCT" and token.value in {"{", "}"}
        )
        if brace_depth > 0:
            continue

        execute_source(source)
        source_lines.clear()
        brace_depth = 0

    if source_lines:
        execute_source("\n".join(source_lines) + "\n")


_IDE_PAGE = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PyCompiler Studio</title>
<style>
:root{color-scheme:dark;--bg:#1e1e1e;--panel:#252526;--line:#333;--muted:#858585;--text:#ccc;--blue:#007acc}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px "Segoe UI",sans-serif;height:100vh;display:flex;flex-direction:column}
button{border:0;color:inherit;background:transparent;font:inherit;cursor:pointer}button:hover{background:#ffffff18}
header{height:42px;background:#323233;display:flex;align-items:center;padding:0 14px;gap:14px;border-bottom:1px solid #222}
.brand{font-weight:600;color:#fff}.brand span{color:#4fc1ff}.workspace{color:#aaa;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.actions{display:flex;gap:6px}.action{padding:6px 10px;border-radius:4px}.primary{background:#0e639c;color:#fff}.primary:hover{background:#1177bb}
main{display:flex;flex:1;min-height:0}.activity{width:48px;background:#333;display:flex;flex-direction:column;align-items:center;padding-top:12px;gap:18px;color:#aaa;font-size:18px}
.activity .selected{color:#fff;border-left:2px solid #4fc1ff;padding-left:9px}
aside{width:240px;background:var(--panel);border-right:1px solid #111;display:flex;flex-direction:column;min-width:170px}
.side-title{height:36px;padding:12px 14px 8px;font-size:11px;letter-spacing:.08em;color:#bbb}
.tree{overflow:auto;padding:2px 0;flex:1}.tree button{display:block;width:100%;text-align:left;padding:5px 12px;color:#bbb;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tree button:hover,.tree button.active{background:#37373d;color:#fff}
.editor-area{display:flex;flex-direction:column;flex:1;min-width:0}.tabs{height:36px;background:#252526;display:flex;align-items:stretch;border-bottom:1px solid #111}
.tab{padding:10px 14px;border-right:1px solid #1e1e1e;border-top:1px solid var(--blue);color:#fff}
.editor-wrap{display:flex;flex:1;min-height:0;background:#1e1e1e;font:14px Consolas,"Courier New",monospace;line-height:21px}
.gutter{width:48px;overflow:hidden;text-align:right;padding:12px 10px;color:#6e7681;user-select:none;white-space:pre}
textarea{resize:none;flex:1;min-width:0;border:0;outline:0;background:transparent;color:#d4d4d4;padding:12px 14px;white-space:pre;overflow:auto;tab-size:4;font:inherit;line-height:inherit}
.bottom{height:210px;min-height:120px;border-top:1px solid #111;background:#1e1e1e;display:flex;flex-direction:column}
.panel-tabs{height:35px;border-bottom:1px solid #333;display:flex;align-items:center;gap:18px;padding:0 14px;font-size:11px;color:#aaa}
.panel-tabs strong{height:35px;padding-top:12px;color:#fff;border-bottom:1px solid #4fc1ff}.output{padding:10px 14px;overflow:auto;white-space:pre-wrap;font:13px Consolas,monospace;color:#d4d4d4;flex:1}
footer{height:23px;background:#007acc;color:white;display:flex;align-items:center;justify-content:space-between;padding:0 10px;font-size:11px}
.hint{color:#888}
@media(max-width:700px){aside{width:155px}.activity{display:none}.workspace{display:none}.bottom{height:160px}}
</style>
</head>
<body>
<header><div class="brand"><span>Py</span>Compiler Studio</div><div class="workspace" id="workspace">Yerel çalışma alanı</div>
<div class="actions"><button class="action" id="new">+ Yeni</button><button class="action" id="save">Kaydet</button><button class="action" id="compile">Derle</button><button class="action primary" id="run">▶ Çalıştır</button></div></header>
<main><div class="activity"><div class="selected" title="Dosya gezgini">▤</div><div title="Ara">⌕</div><div title="Ayarlar">⚙</div></div>
<aside><div class="side-title">GEZGİN</div><div class="tree" id="files"></div></aside>
<section class="editor-area"><div class="tabs"><div class="tab" id="tab">Hoş geldiniz</div></div>
<div class="editor-wrap"><div class="gutter" id="gutter">1</div><textarea id="editor" spellcheck="false" aria-label="Kod editörü" placeholder="Kodunuzu buraya yazın..."></textarea></div>
<div class="bottom"><div class="panel-tabs"><strong>ÇIKTI</strong><span>DERLEYİCİ</span><span class="hint" id="message">Çalıştırma veya derleme bekleniyor</span></div><div class="output" id="output">PyCompiler Studio hazır. .pc dosyalarını düzenleyip çalıştırabilirsiniz.</div></div></section></main>
<footer><span>● Hazır</span><span id="position">Satır 1, Sütun 1　 |　 PyCompiler</span></footer>
<script>
const editor=document.querySelector("#editor"), files=document.querySelector("#files"), output=document.querySelector("#output");
let activePath="";
function status(text){document.querySelector("#message").textContent=text}
function setGutter(){document.querySelector("#gutter").textContent=Array.from({length:editor.value.split("\n").length},(_,i)=>i+1).join("\n")}
function setPosition(){const before=editor.value.slice(0,editor.selectionStart).split("\n");document.querySelector("#position").textContent=`Satır ${before.length}, Sütun ${before.at(-1).length+1}　 |　 ${activePath||"Yeni dosya"}`}
async function api(url, options){const response=await fetch(url,options);const data=await response.json();if(!response.ok)throw Error(data.error||"İstek başarısız");return data}
function showError(error){output.textContent=error.message;status("Hata")}
async function refreshFiles(){try{const data=await api("/api/files");files.replaceChildren();for(const path of data.files){const button=document.createElement("button");button.textContent="　"+path;button.title=path;button.className=path===activePath?"active":"";button.onclick=()=>openFile(path);files.append(button)}}catch(error){showError(error)}}
async function openFile(path){try{const data=await api("/api/read?path="+encodeURIComponent(path));activePath=data.path;editor.value=data.content;document.querySelector("#tab").textContent=path;document.querySelector("#workspace").textContent=data.workspace;setGutter();setPosition();await refreshFiles();status("Dosya açıldı")}catch(error){showError(error)}}
async function saveFile(){if(!activePath){activePath=prompt("Dosya adı (ör. main.pc):","main.pc")||"";if(!activePath)return}try{await api("/api/save",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:activePath,content:editor.value})});document.querySelector("#tab").textContent=activePath;status("Kaydedildi");await refreshFiles()}catch(error){showError(error)}}
async function execute(mode){try{if(activePath&&!activePath.endsWith(".pc"))throw Error("Yalnızca .pc dosyaları derlenebilir.");const data=await api("/api/"+mode,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:editor.value})});output.textContent=data.output;status(mode==="run"?"Çalıştırma tamamlandı":"Derleme tamamlandı")}catch(error){showError(error)}}
document.querySelector("#new").onclick=()=>{activePath="";editor.value="";document.querySelector("#tab").textContent="Yeni dosya";setGutter();setPosition();editor.focus();status("Yeni dosya")}
document.querySelector("#save").onclick=saveFile;document.querySelector("#run").onclick=()=>execute("run");document.querySelector("#compile").onclick=()=>execute("compile");
editor.addEventListener("input",setGutter);editor.addEventListener("click",setPosition);editor.addEventListener("keyup",setPosition);editor.addEventListener("scroll",()=>document.querySelector("#gutter").scrollTop=editor.scrollTop);
editor.addEventListener("keydown",event=>{if(event.key==="Tab"){event.preventDefault();const start=editor.selectionStart,end=editor.selectionEnd;editor.setRangeText("    ",start,end,"end");setGutter()}if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"){event.preventDefault();saveFile()}if((event.ctrlKey||event.metaKey)&&event.key==="Enter"){event.preventDefault();execute("run")}});
refreshFiles();setGutter();setPosition();
</script></body></html>"""


def _run_compiled_source(python_source: str) -> str:
    runner = (
        "import sys\n"
        "written = 0\n"
        "def limited_print(*values, sep=' ', end='\\n'):\n"
        "    global written\n"
        "    text = sep.join(map(str, values)) + end\n"
        "    written += len(text)\n"
        "    if written > 1000000:\n"
        "        raise RuntimeError('output exceeded 1 MB')\n"
        "    sys.stdout.write(text)\n"
        "source = sys.stdin.read()\n"
        "exec(compile(source, '<pycompiler>', 'exec'), "
        "{'__builtins__': {'print': limited_print}})\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", runner],
            input=python_source,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        partial = error.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        return f"{partial}\nExecution stopped after 3 seconds."
    output = result.stdout
    if result.stderr:
        output += ("\n" if output else "") + result.stderr
    return output or ("Program finished with no output." if result.returncode == 0 else "")


def run_ide(workspace: str | Path = ".", host: str = "127.0.0.1", port: int = 8765,
            open_browser: bool = True) -> None:
    """Start a local browser-based editor for .pc programs."""
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise ValueError(f"workspace is not a directory: {root}")

    class IDEHandler(BaseHTTPRequestHandler):
        server_version = "PyCompilerStudio/1.0"

        def _send(self, status: int, data: object, content_type: str = "application/json") -> None:
            body = data if isinstance(data, bytes) else json.dumps(
                data, ensure_ascii=False
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _path(self, relative: str) -> Path:
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError("path must stay inside the workspace")
            resolved = (root / candidate).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise ValueError("path must stay inside the workspace") from error
            return resolved

        def _json_body(self) -> dict[str, object]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValueError("invalid Content-Length") from error
            if length < 0 or length > 262144:
                raise ValueError("request body must be smaller than 256 KB")
            try:
                data = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ValueError("request body must be valid JSON") from error
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _check_origin(self) -> bool:
            origin = self.headers.get("Origin")
            host_header = self.headers.get("Host", "")
            host_name = host_header.rsplit(":", 1)[0].strip("[]").lower()
            try:
                host_port = int(host_header.rsplit(":", 1)[1])
            except (IndexError, ValueError):
                return False
            if host_name not in {"127.0.0.1", "localhost"} or host_port != self.server.server_port:
                return False
            if not origin:
                return True
            parsed = urlsplit(origin)
            return (
                parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost"}
                and parsed.port == self.server.server_port
            )

        def do_GET(self) -> None:
            if not self._check_origin():
                self._send(403, {"error": "request is not from this local IDE"})
                return
            request = urlsplit(self.path)
            if request.path == "/":
                self._send(200, _IDE_PAGE.encode("utf-8"), "text/html")
                return
            try:
                if request.path == "/api/files":
                    found: list[str] = []
                    for directory, names, filenames in os.walk(root):
                        names[:] = [name for name in names if name not in {
                            ".git", ".venv", "venv", "__pycache__", "node_modules"
                        }]
                        for name in filenames:
                            relative = (Path(directory) / name).relative_to(root)
                            if len(found) >= 1000:
                                break
                            found.append(relative.as_posix())
                        if len(found) >= 1000:
                            break
                    self._send(200, {"files": sorted(found)})
                    return
                if request.path == "/api/read":
                    relative = parse_qs(request.query).get("path", [""])[0]
                    path = self._path(relative)
                    if not path.is_file():
                        self._send(404, {"error": "file not found"})
                        return
                    if path.stat().st_size > 262144:
                        self._send(413, {"error": "file is larger than 256 KB"})
                        return
                    self._send(200, {
                        "path": path.relative_to(root).as_posix(),
                        "content": path.read_text(encoding="utf-8"),
                        "workspace": root.name,
                    })
                    return
                self._send(404, {"error": "not found"})
            except (OSError, UnicodeError, ValueError) as error:
                self._send(400, {"error": str(error)})

        def do_POST(self) -> None:
            if not self._check_origin():
                self._send(403, {"error": "request is not from this local IDE"})
                return
            try:
                data = self._json_body()
                if self.path == "/api/save":
                    relative = data.get("path")
                    content = data.get("content")
                    if not isinstance(relative, str) or not isinstance(content, str):
                        raise ValueError("path and content must be strings")
                    path = self._path(relative)
                    if path == root:
                        raise ValueError("path must name a file")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8", newline="")
                    self._send(200, {"path": path.relative_to(root).as_posix()})
                    return
                content = data.get("content")
                if not isinstance(content, str):
                    raise ValueError("content must be a string")
                if len(content.encode("utf-8")) > 262144:
                    raise ValueError("source must be smaller than 256 KB")
                python_source = compile_source(content)
                if self.path == "/api/compile":
                    self._send(200, {"output": python_source or "# No code to compile."})
                    return
                if self.path == "/api/run":
                    self._send(200, {"output": _run_compiled_source(python_source)})
                    return
                self._send(404, {"error": "not found"})
            except CompileError as error:
                self._send(400, {"error": str(error)})
            except (OSError, UnicodeError, ValueError) as error:
                self._send(400, {"error": str(error)})

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), IDEHandler)
    server.daemon_threads = True
    address, actual_port = server.server_address[:2]
    url = f"http://{address}:{actual_port}/"
    print(f"PyCompiler Studio is running at {url}")
    print("Only open this local IDE for code you trust; it can edit workspace files.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPyCompiler Studio stopped.")
    finally:
        server.server_close()


def main(argv: Sequence[str] | None = None) -> int:
    argument_parser = argparse.ArgumentParser(
        description="Compile and run PyCompiler programs, or launch the local IDE."
    )
    argument_parser.add_argument(
        "file",
        nargs="?",
        default="-",
        help="source file to compile (default: standard input)",
    )
    argument_parser.add_argument(
        "--run",
        action="store_true",
        help="execute the compiled program instead of printing generated Python",
    )
    argument_parser.add_argument(
        "-o",
        "--output",
        help="write generated Python to this file instead of standard output",
    )
    argument_parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="start an interactive prompt and preserve variables between statements",
    )
    argument_parser.add_argument(
        "--ide",
        action="store_true",
        help="launch the local browser-based editor",
    )
    argument_parser.add_argument(
        "--workspace",
        default=".",
        help="workspace directory used by --ide (default: current directory)",
    )
    argument_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="local IDE port (default: 8765; use 0 for an available port)",
    )
    argument_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser automatically",
    )
    arguments = argument_parser.parse_args(argv)

    if arguments.ide:
        if arguments.file != "-" or arguments.run or arguments.output or arguments.interactive:
            argument_parser.error("--ide cannot be combined with compiler input options")
        if not 0 <= arguments.port <= 65535:
            argument_parser.error("--port must be between 0 and 65535")
        try:
            run_ide(arguments.workspace, port=arguments.port, open_browser=not arguments.no_browser)
        except (OSError, ValueError) as error:
            argument_parser.error(str(error))
        return 0
    if arguments.interactive and arguments.file != "-":
        argument_parser.error("--interactive does not accept a source file")
    if arguments.interactive and arguments.run:
        argument_parser.error("--interactive cannot be combined with --run")
    if arguments.output and (arguments.run or arguments.interactive):
        argument_parser.error("--output cannot be combined with --run or --interactive")

    if arguments.interactive:
        run_interactive()
        return 0

    try:
        source = (
            sys.stdin.read()
            if arguments.file == "-"
            else Path(arguments.file).read_text(encoding="utf-8-sig")
        )
        if arguments.run:
            run_source(source)
        elif arguments.output:
            Path(arguments.output).write_text(compile_source(source), encoding="utf-8")
        else:
            sys.stdout.write(compile_source(source))
    except CompileError as error:
        print(error, file=sys.stderr)
        return 1
    except OSError as error:
        argument_parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
