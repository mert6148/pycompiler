use std::collections::{HashMap, HashSet};
use std::fmt;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::time::Duration;

const MAX_REQUEST_SIZE: usize = 1024 * 1024;
const MAX_EXECUTION_STEPS: usize = 1_000_000;
const ADDRESS: &str = "127.0.0.1:3030";

fn main() -> std::io::Result<()> {
    let listener = TcpListener::bind(ADDRESS)?;
    println!("Rust IDE is ready at http://{ADDRESS}");

    for connection in listener.incoming() {
        match connection {
            Ok(stream) => {
                if let Err(error) = handle_connection(stream) {
                    eprintln!("Request failed: {error}");
                }
            }
            Err(error) => eprintln!("Connection failed: {error}"),
        }
    }

    Ok(())
}

fn handle_connection(mut stream: TcpStream) -> std::io::Result<()> {
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;

    let response = match read_request(&mut stream) {
        Ok((method, path, body)) => route(&method, &path, &body),
        Err((status, message)) => Response::text(status, message),
    };

    write!(
        stream,
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\nContent-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'\r\n\r\n",
        response.status,
        response.reason(),
        response.content_type,
        response.body.len()
    )?;
    stream.write_all(&response.body)
}

fn read_request(stream: &mut TcpStream) -> Result<(String, String, Vec<u8>), (u16, String)> {
    let mut request = Vec::new();
    let mut chunk = [0; 4096];
    let header_end = loop {
        if request.len() > MAX_REQUEST_SIZE {
            return Err((413, "Request is too large.".into()));
        }
        let count = stream
            .read(&mut chunk)
            .map_err(|error| (400, format!("Could not read request: {error}")))?;
        if count == 0 {
            return Err((400, "Incomplete request.".into()));
        }
        request.extend_from_slice(&chunk[..count]);
        if let Some(position) = request.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
            break position + 4;
        }
    };

    let headers = std::str::from_utf8(&request[..header_end])
        .map_err(|_| (400, "Invalid request headers.".into()))?;
    let mut lines = headers.split("\r\n");
    let mut request_line = lines
        .next()
        .ok_or_else(|| (400, "Missing request line.".into()))?
        .split_whitespace();
    let method = request_line
        .next()
        .ok_or_else(|| (400, "Missing HTTP method.".into()))?
        .to_owned();
    let path = request_line
        .next()
        .ok_or_else(|| (400, "Missing request path.".into()))?
        .to_owned();
    let content_length = lines
        .filter_map(|line| line.split_once(':'))
        .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
        .map(|(_, value)| value.trim().parse::<usize>())
        .transpose()
        .map_err(|_| (400, "Invalid content length.".into()))?
        .unwrap_or(0);

    if content_length > MAX_REQUEST_SIZE {
        return Err((413, "Request is too large.".into()));
    }

    let body_start = header_end;
    let expected_length = body_start + content_length;
    while request.len() < expected_length {
        let count = stream
            .read(&mut chunk)
            .map_err(|error| (400, format!("Could not read request body: {error}")))?;
        if count == 0 {
            return Err((400, "Incomplete request body.".into()));
        }
        request.extend_from_slice(&chunk[..count]);
    }

    Ok((method, path, request[body_start..expected_length].to_vec()))
}

fn route(method: &str, path: &str, body: &[u8]) -> Response {
    if method == "GET" {
        return match path {
            "/" => Response::html(include_bytes!("../web/index.html")),
            "/style.css" => Response::css(include_bytes!("../web/style.css")),
            "/app.js" => Response::javascript(include_bytes!("../web/app.js")),
            _ => Response::text(404, "Not found."),
        };
    }

    if method == "POST" && path == "/api/run" {
        return match std::str::from_utf8(body) {
            Ok(source) => match compile_and_run(source) {
                Ok(output) => Response::text(200, output),
                Err(error) => Response::text(400, error.to_string()),
            },
            Err(_) => Response::text(400, "Source code must be valid UTF-8."),
        };
    }

    Response::text(404, "Not found.")
}

struct Response {
    status: u16,
    content_type: &'static str,
    body: Vec<u8>,
}

impl Response {
    fn text(status: u16, body: impl Into<String>) -> Self {
        Self {
            status,
            content_type: "text/plain; charset=utf-8",
            body: body.into().into_bytes(),
        }
    }

    fn html(body: &'static [u8]) -> Self {
        Self::asset("text/html; charset=utf-8", body)
    }

    fn css(body: &'static [u8]) -> Self {
        Self::asset("text/css; charset=utf-8", body)
    }

    fn javascript(body: &'static [u8]) -> Self {
        Self::asset("text/javascript; charset=utf-8", body)
    }

    fn asset(content_type: &'static str, body: &'static [u8]) -> Self {
        Self {
            status: 200,
            content_type,
            body: body.to_vec(),
        }
    }

    fn reason(&self) -> &'static str {
        match self.status {
            200 => "OK",
            400 => "Bad Request",
            404 => "Not Found",
            413 => "Payload Too Large",
            _ => "Internal Server Error",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
struct CompileError {
    message: String,
}

impl CompileError {
    fn new(line: usize, column: usize, message: impl fmt::Display) -> Self {
        Self {
            message: format!("{line}:{column}: {message}"),
        }
    }
}

impl fmt::Display for CompileError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}", self.message)
    }
}

impl std::error::Error for CompileError {}

#[derive(Debug, Clone, PartialEq)]
enum TokenKind {
    Let,
    Print,
    If,
    Else,
    While,
    Identifier(String),
    Number(i64),
    Plus,
    Minus,
    Star,
    Slash,
    Equal,
    EqualEqual,
    BangEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    Semicolon,
    LeftParen,
    RightParen,
    LeftBrace,
    RightBrace,
    Eof,
}

#[derive(Debug, Clone)]
struct Token {
    kind: TokenKind,
    line: usize,
    column: usize,
}

fn lex(source: &str) -> Result<Vec<Token>, CompileError> {
    let characters: Vec<char> = source.chars().collect();
    let (mut index, mut line, mut column) = (0, 1, 1);
    let mut tokens = Vec::new();

    while index < characters.len() {
        let character = characters[index];
        if character.is_whitespace() {
            if character == '\n' {
                line += 1;
                column = 1;
            } else {
                column += 1;
            }
            index += 1;
            continue;
        }

        if character == '/' && characters.get(index + 1) == Some(&'/') {
            while index < characters.len() && characters[index] != '\n' {
                index += 1;
                column += 1;
            }
            continue;
        }

        let (token_line, token_column) = (line, column);
        let kind = if character.is_ascii_digit() {
            let start = index;
            while characters.get(index).is_some_and(|c| c.is_ascii_digit()) {
                index += 1;
                column += 1;
            }
            let value: String = characters[start..index].iter().collect();
            let number = value.parse::<i64>().map_err(|_| {
                CompileError::new(token_line, token_column, "integer literal is too large")
            })?;
            tokens.push(Token {
                kind: TokenKind::Number(number),
                line: token_line,
                column: token_column,
            });
            continue;
        } else if character.is_ascii_alphabetic() || character == '_' {
            let start = index;
            while characters
                .get(index)
                .is_some_and(|c| c.is_ascii_alphanumeric() || *c == '_')
            {
                index += 1;
                column += 1;
            }
            let word: String = characters[start..index].iter().collect();
            match word.as_str() {
                "let" => TokenKind::Let,
                "print" => TokenKind::Print,
                "if" => TokenKind::If,
                "else" => TokenKind::Else,
                "while" => TokenKind::While,
                _ => TokenKind::Identifier(word),
            }
        } else {
            let two_character_token = match (character, characters.get(index + 1)) {
                ('=', Some('=')) => Some(TokenKind::EqualEqual),
                ('!', Some('=')) => Some(TokenKind::BangEqual),
                ('<', Some('=')) => Some(TokenKind::LessEqual),
                ('>', Some('=')) => Some(TokenKind::GreaterEqual),
                _ => None,
            };
            if let Some(kind) = two_character_token {
                index += 2;
                column += 2;
                kind
            } else {
                index += 1;
                column += 1;
                match character {
                    '+' => TokenKind::Plus,
                    '-' => TokenKind::Minus,
                    '*' => TokenKind::Star,
                    '/' => TokenKind::Slash,
                    '=' => TokenKind::Equal,
                    '<' => TokenKind::Less,
                    '>' => TokenKind::Greater,
                    ';' => TokenKind::Semicolon,
                    '(' => TokenKind::LeftParen,
                    ')' => TokenKind::RightParen,
                    '{' => TokenKind::LeftBrace,
                    '}' => TokenKind::RightBrace,
                    _ => {
                        return Err(CompileError::new(
                            token_line,
                            token_column,
                            format!("unexpected character '{character}'"),
                        ));
                    }
                }
            }
        };
        tokens.push(Token {
            kind,
            line: token_line,
            column: token_column,
        });
    }

    tokens.push(Token {
        kind: TokenKind::Eof,
        line,
        column,
    });
    Ok(tokens)
}

#[derive(Debug, Clone)]
enum Instruction {
    Push(i64),
    Load(String),
    Store(String),
    Add,
    Subtract,
    Multiply,
    Divide,
    Equal,
    NotEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    Negate,
    Print,
    Jump(usize),
    JumpIfFalse(usize),
}

struct Parser {
    tokens: Vec<Token>,
    current: usize,
    declared: HashSet<String>,
    code: Vec<Instruction>,
}

impl Parser {
    fn new(tokens: Vec<Token>) -> Self {
        Self {
            tokens,
            current: 0,
            declared: HashSet::new(),
            code: Vec::new(),
        }
    }

    fn compile(mut self) -> Result<Vec<Instruction>, CompileError> {
        while !self.check(&TokenKind::Eof) {
            self.statement()?;
        }
        Ok(self.code)
    }

    fn statement(&mut self) -> Result<(), CompileError> {
        if self.matches(&TokenKind::If) {
            self.expression(0)?;
            let false_jump = self.emit_jump_if_false();
            self.block()?;

            if self.matches(&TokenKind::Else) {
                let end_jump = self.emit_jump();
                self.patch_jump(false_jump);
                self.block()?;
                self.patch_jump(end_jump);
            } else {
                self.patch_jump(false_jump);
            }
            return Ok(());
        }

        if self.matches(&TokenKind::While) {
            let loop_start = self.code.len();
            self.expression(0)?;
            let exit_jump = self.emit_jump_if_false();
            self.block()?;
            self.code.push(Instruction::Jump(loop_start));
            self.patch_jump(exit_jump);
            return Ok(());
        }

        if self.matches(&TokenKind::Let) {
            let name = self.take_identifier("expected a variable name after 'let'")?;
            if self.declared.contains(&name) {
                return Err(self.error(format!("'{name}' is already declared")));
            }
            self.expect(&TokenKind::Equal, "expected '=' after variable name")?;
            self.expression(0)?;
            self.expect(&TokenKind::Semicolon, "expected ';' after declaration")?;
            self.declared.insert(name.clone());
            self.code.push(Instruction::Store(name));
            return Ok(());
        }

        if self.matches(&TokenKind::Print) {
            self.expression(0)?;
            self.expect(&TokenKind::Semicolon, "expected ';' after print expression")?;
            self.code.push(Instruction::Print);
            return Ok(());
        }

        if let TokenKind::Identifier(name) = self.peek().kind.clone() {
            let token = self.advance().clone();
            if !self.declared.contains(&name) {
                return Err(CompileError::new(
                    token.line,
                    token.column,
                    format!("undefined variable '{name}'"),
                ));
            }
            self.expect(&TokenKind::Equal, "expected '=' after variable name")?;
            self.expression(0)?;
            self.expect(&TokenKind::Semicolon, "expected ';' after assignment")?;
            self.code.push(Instruction::Store(name));
            return Ok(());
        }

        Err(self.error("expected a declaration, assignment, print, if, or while statement"))
    }

    fn expression(&mut self, minimum_precedence: u8) -> Result<(), CompileError> {
        if self.matches(&TokenKind::Minus) {
            self.expression(4)?;
            self.code.push(Instruction::Negate);
        } else if self.matches(&TokenKind::LeftParen) {
            self.expression(0)?;
            self.expect(&TokenKind::RightParen, "expected ')' after expression")?;
        } else {
            let token = self.advance().clone();
            match token.kind {
                TokenKind::Number(value) => self.code.push(Instruction::Push(value)),
                TokenKind::Identifier(name) => {
                    if !self.declared.contains(&name) {
                        return Err(CompileError::new(
                            token.line,
                            token.column,
                            format!("undefined variable '{name}'"),
                        ));
                    }
                    self.code.push(Instruction::Load(name));
                }
                _ => {
                    return Err(CompileError::new(
                        token.line,
                        token.column,
                        "expected a number, variable, or parenthesized expression",
                    ));
                }
            }
        }

        loop {
            let (precedence, instruction) = match self.peek().kind {
                TokenKind::EqualEqual => (1, Instruction::Equal),
                TokenKind::BangEqual => (1, Instruction::NotEqual),
                TokenKind::Less => (1, Instruction::Less),
                TokenKind::LessEqual => (1, Instruction::LessEqual),
                TokenKind::Greater => (1, Instruction::Greater),
                TokenKind::GreaterEqual => (1, Instruction::GreaterEqual),
                TokenKind::Plus => (2, Instruction::Add),
                TokenKind::Minus => (2, Instruction::Subtract),
                TokenKind::Star => (3, Instruction::Multiply),
                TokenKind::Slash => (3, Instruction::Divide),
                _ => break,
            };
            if precedence < minimum_precedence {
                break;
            }
            self.advance();
            self.expression(precedence + 1)?;
            self.code.push(instruction);
        }
        Ok(())
    }

    fn block(&mut self) -> Result<(), CompileError> {
        self.expect(&TokenKind::LeftBrace, "expected '{' before block")?;
        let outer_variables = self.declared.clone();
        while !self.check(&TokenKind::RightBrace) {
            if self.check(&TokenKind::Eof) {
                return Err(self.error("expected '}' after block"));
            }
            self.statement()?;
        }
        self.advance();
        self.declared = outer_variables;
        Ok(())
    }

    fn emit_jump(&mut self) -> usize {
        let instruction = self.code.len();
        self.code.push(Instruction::Jump(usize::MAX));
        instruction
    }

    fn emit_jump_if_false(&mut self) -> usize {
        let instruction = self.code.len();
        self.code.push(Instruction::JumpIfFalse(usize::MAX));
        instruction
    }

    fn patch_jump(&mut self, instruction: usize) {
        let target = self.code.len();
        match &mut self.code[instruction] {
            Instruction::Jump(destination) | Instruction::JumpIfFalse(destination) => {
                *destination = target;
            }
            _ => unreachable!("only jump instructions can be patched"),
        }
    }

    fn take_identifier(&mut self, message: &str) -> Result<String, CompileError> {
        let token = self.advance().clone();
        match token.kind {
            TokenKind::Identifier(name) => Ok(name),
            _ => Err(CompileError::new(token.line, token.column, message)),
        }
    }

    fn expect(&mut self, kind: &TokenKind, message: &str) -> Result<(), CompileError> {
        if self.matches(kind) {
            Ok(())
        } else {
            Err(self.error(message))
        }
    }

    fn matches(&mut self, kind: &TokenKind) -> bool {
        if self.check(kind) {
            self.advance();
            true
        } else {
            false
        }
    }

    fn check(&self, kind: &TokenKind) -> bool {
        std::mem::discriminant(&self.peek().kind) == std::mem::discriminant(kind)
    }

    fn advance(&mut self) -> &Token {
        let index = self.current;
        if !self.check(&TokenKind::Eof) {
            self.current += 1;
        }
        &self.tokens[index]
    }

    fn peek(&self) -> &Token {
        &self.tokens[self.current]
    }

    fn error(&self, message: impl fmt::Display) -> CompileError {
        CompileError::new(self.peek().line, self.peek().column, message)
    }
}

fn compile_and_run(source: &str) -> Result<String, CompileError> {
    let code = Parser::new(lex(source)?).compile()?;
    execute(&code)
}

fn execute(code: &[Instruction]) -> Result<String, CompileError> {
    let mut stack = Vec::new();
    let mut variables = HashMap::new();
    let mut output = String::new();
    let mut instruction_pointer = 0;
    let mut executed_instructions = 0;

    while instruction_pointer < code.len() {
        executed_instructions += 1;
        if executed_instructions > MAX_EXECUTION_STEPS {
            return Err(CompileError {
                message: format!(
                    "runtime error: execution limit exceeded ({MAX_EXECUTION_STEPS} instructions)"
                ),
            });
        }
        let instruction = &code[instruction_pointer];
        match instruction {
            Instruction::Push(value) => stack.push(*value),
            Instruction::Load(name) => {
                let value = variables.get(name).copied().ok_or_else(|| CompileError {
                    message: format!("runtime error: undefined variable '{name}'"),
                })?;
                stack.push(value);
            }
            Instruction::Store(name) => {
                let value = stack.pop().ok_or_else(stack_underflow)?;
                variables.insert(name.clone(), value);
            }
            Instruction::Add => apply_binary(&mut stack, i64::checked_add, "addition")?,
            Instruction::Subtract => apply_binary(&mut stack, i64::checked_sub, "subtraction")?,
            Instruction::Multiply => apply_binary(&mut stack, i64::checked_mul, "multiplication")?,
            Instruction::Divide => {
                let right = stack.pop().ok_or_else(stack_underflow)?;
                let left = stack.pop().ok_or_else(stack_underflow)?;
                if right == 0 {
                    return Err(CompileError {
                        message: "runtime error: division by zero".into(),
                    });
                }
                stack.push(
                    left.checked_div(right)
                        .ok_or_else(|| arithmetic_overflow("division"))?,
                );
            }
            Instruction::Equal => apply_comparison(&mut stack, |left, right| left == right)?,
            Instruction::NotEqual => apply_comparison(&mut stack, |left, right| left != right)?,
            Instruction::Less => apply_comparison(&mut stack, |left, right| left < right)?,
            Instruction::LessEqual => apply_comparison(&mut stack, |left, right| left <= right)?,
            Instruction::Greater => apply_comparison(&mut stack, |left, right| left > right)?,
            Instruction::GreaterEqual => apply_comparison(&mut stack, |left, right| left >= right)?,
            Instruction::Negate => {
                let value = stack.pop().ok_or_else(stack_underflow)?;
                stack.push(
                    value
                        .checked_neg()
                        .ok_or_else(|| arithmetic_overflow("negation"))?,
                );
            }
            Instruction::Print => {
                let value = stack.pop().ok_or_else(stack_underflow)?;
                output.push_str(&format!("{value}\n"));
            }
            Instruction::Jump(target) => {
                instruction_pointer = *target;
                continue;
            }
            Instruction::JumpIfFalse(target) => {
                if stack.pop().ok_or_else(stack_underflow)? == 0 {
                    instruction_pointer = *target;
                    continue;
                }
            }
        }
        instruction_pointer += 1;
    }

    Ok(output)
}

fn apply_comparison(
    stack: &mut Vec<i64>,
    comparison: fn(i64, i64) -> bool,
) -> Result<(), CompileError> {
    let right = stack.pop().ok_or_else(stack_underflow)?;
    let left = stack.pop().ok_or_else(stack_underflow)?;
    stack.push(i64::from(comparison(left, right)));
    Ok(())
}

fn apply_binary(
    stack: &mut Vec<i64>,
    operation: fn(i64, i64) -> Option<i64>,
    name: &str,
) -> Result<(), CompileError> {
    let right = stack.pop().ok_or_else(stack_underflow)?;
    let left = stack.pop().ok_or_else(stack_underflow)?;
    stack.push(operation(left, right).ok_or_else(|| arithmetic_overflow(name))?);
    Ok(())
}

fn stack_underflow() -> CompileError {
    CompileError {
        message: "runtime error: invalid compiler stack state".into(),
    }
}

fn arithmetic_overflow(operation: &str) -> CompileError {
    CompileError {
        message: format!("runtime error: integer overflow during {operation}"),
    }
}

#[cfg(test)]
mod tests {
    use super::compile_and_run;

    #[test]
    fn compiles_variables_and_respects_operator_precedence() {
        let output = compile_and_run("let answer = 2 + 3 * 4; print answer;")
            .expect("valid program should run");
        assert_eq!(output, "14\n");
    }

    #[test]
    fn supports_assignment_and_parentheses() {
        let output = compile_and_run("let value = 2; value = (value + 1) * 3; print value;")
            .expect("valid program should run");
        assert_eq!(output, "9\n");
    }

    #[test]
    fn reports_undefined_variables_with_source_location() {
        let error = compile_and_run("print missing;").expect_err("undefined name should fail");
        assert!(error
            .to_string()
            .contains("1:7: undefined variable 'missing'"));
    }

    #[test]
    fn reports_division_by_zero() {
        let error =
            compile_and_run("print 8 / (3 - 3);").expect_err("division by zero should fail");
        assert_eq!(error.to_string(), "runtime error: division by zero");
    }

    #[test]
    fn selects_if_else_branch_from_comparison() {
        let output = compile_and_run("let value = 5; if value >= 5 { print 1; } else { print 0; }")
            .expect("valid conditional should run");
        assert_eq!(output, "1\n");
    }

    #[test]
    fn supports_all_comparison_operators() {
        let output = compile_and_run(
            "print 1 == 1; print 1 != 2; print 1 < 2; print 2 <= 2; print 3 > 2; print 3 >= 3;",
        )
        .expect("valid comparisons should run");
        assert_eq!(output, "1\n1\n1\n1\n1\n1\n");
    }

    #[test]
    fn runs_while_loop_and_preserves_outer_variables() {
        let output = compile_and_run(
            "let total = 0; let index = 1; while index <= 5 { total = total + index; index = index + 1; } print total;",
        )
        .expect("valid loop should run");
        assert_eq!(output, "15\n");
    }

    #[test]
    fn keeps_block_variables_out_of_outer_scope() {
        let error = compile_and_run("if 1 { let inside = 3; } print inside;")
            .expect_err("block-local variable should not escape");
        assert!(error.to_string().contains("undefined variable 'inside'"));
    }

    #[test]
    fn reports_unclosed_blocks() {
        let error = compile_and_run("if 1 { print 2;").expect_err("unclosed block should fail");
        assert!(error.to_string().contains("expected '}' after block"));
    }

    #[test]
    fn stops_non_terminating_loops_at_the_execution_limit() {
        let error = compile_and_run("while 1 {}").expect_err("infinite loop should be stopped");
        assert!(error.to_string().contains("execution limit exceeded"));
    }
}
