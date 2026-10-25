"""A small compiler for an educational, block-structured language.

Example:
    let count = 3
    while count > 0 {
        print(count)
        count = count - 1
    }

Run ``python compiler.py program.pc`` to emit Python, or add ``--run`` to
execute the compiled program.
"""

from __future__ import annotations

import argparse
import ast
import keyword
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


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


def main(argv: Sequence[str] | None = None) -> int:
    argument_parser = argparse.ArgumentParser(
        description="Compile a small educational language to Python."
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
    arguments = argument_parser.parse_args(argv)

    try:
        source = (
            sys.stdin.read()
            if arguments.file == "-"
            else Path(arguments.file).read_text(encoding="utf-8")
        )
        if arguments.run:
            run_source(source)
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