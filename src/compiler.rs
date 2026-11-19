//! Rusty language lexer, parser, AST interpreter, and public compiler API.

use std::collections::HashMap;
use std::fmt;

const MAX_EXECUTION_STEPS: usize = 1_000_000;
const MAX_SOURCE_LENGTH: usize = 1024 * 1024;
const MAX_BLOCK_DEPTH: usize = 128;
// Keep recursive expression parsing and evaluation bounded for untrusted input.
const MAX_EXPRESSION_DEPTH: usize = 128;

/// A source or runtime error produced by the Rusty compiler.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompileError {
    line: Option<usize>,
    column: Option<usize>,
    message: String,
}

impl CompileError {
    fn source(line: usize, column: usize, message: impl Into<String>) -> Self {
        Self {
            line: Some(line),
            column: Some(column),
            message: message.into(),
        }
    }

    fn runtime(message: impl Into<String>) -> Self {
        Self {
            line: None,
            column: None,
            message: format!("runtime error: {}", message.into()),
        }
    }

    /// One-based source line, if this is a source error.
    pub fn line(&self) -> Option<usize> {
        self.line
    }

    /// One-based source column, if this is a source error.
    pub fn column(&self) -> Option<usize> {
        self.column
    }

    /// Human-readable compiler or runtime diagnostic.
    pub fn message(&self) -> &str {
        &self.message
    }

    pub fn is_runtime(&self) -> bool {
        self.line.is_none()
    }
}

impl fmt::Display for CompileError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match (self.line, self.column) {
            (Some(line), Some(column)) => write!(formatter, "{line}:{column}: {}", self.message),
            _ => write!(formatter, "{}", self.message),
        }
    }
}

impl std::error::Error for CompileError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Span {
    line: usize,
    column: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum TokenKind {
    Let,
    Print,
    If,
    Else,
    While,
    Break,
    Continue,
    Identifier(String),
    Integer(i64),
    Plus,
    Minus,
    Star,
    Slash,
    Percent,
    Equal,
    EqualEqual,
    Bang,
    BangEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    AmpAmp,
    PipePipe,
    Semicolon,
    LeftParen,
    RightParen,
    LeftBrace,
    RightBrace,
    Eof,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Token {
    kind: TokenKind,
    span: Span,
}

fn lex(source: &str) -> Result<Vec<Token>, CompileError> {
    if source.len() > MAX_SOURCE_LENGTH {
        return Err(CompileError::source(
            1,
            1,
            format!("source is too large (maximum {MAX_SOURCE_LENGTH} bytes)"),
        ));
    }

    let chars: Vec<char> = source.chars().collect();
    let mut index = 0;
    let mut line = 1;
    let mut column = 1;
    let mut tokens = Vec::new();

    while index < chars.len() {
        let character = chars[index];

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

        if character == '/' && chars.get(index + 1) == Some(&'/') {
            while index < chars.len() && chars[index] != '\n' {
                index += 1;
                column += 1;
            }
            continue;
        }

        let span = Span { line, column };
        let kind = if character.is_ascii_digit() {
            let start = index;
            while chars.get(index).is_some_and(|next| next.is_ascii_digit()) {
                index += 1;
                column += 1;
            }
            let literal: String = chars[start..index].iter().collect();
            let value = literal.parse::<i64>().map_err(|_| {
                CompileError::source(span.line, span.column, "integer literal is too large")
            })?;
            TokenKind::Integer(value)
        } else if character.is_ascii_alphabetic() || character == '_' {
            let start = index;
            while chars
                .get(index)
                .is_some_and(|next| next.is_ascii_alphanumeric() || *next == '_')
            {
                index += 1;
                column += 1;
            }
            let word: String = chars[start..index].iter().collect();
            match word.as_str() {
                "let" => TokenKind::Let,
                "print" => TokenKind::Print,
                "if" => TokenKind::If,
                "else" => TokenKind::Else,
                "while" => TokenKind::While,
                "break" => TokenKind::Break,
                "continue" => TokenKind::Continue,
                _ => TokenKind::Identifier(word),
            }
        } else {
            let pair = chars.get(index + 1).copied();
            let kind = match (character, pair) {
                ('=', Some('=')) => {
                    index += 2;
                    column += 2;
                    TokenKind::EqualEqual
                }
                ('!', Some('=')) => {
                    index += 2;
                    column += 2;
                    TokenKind::BangEqual
                }
                ('<', Some('=')) => {
                    index += 2;
                    column += 2;
                    TokenKind::LessEqual
                }
                ('>', Some('=')) => {
                    index += 2;
                    column += 2;
                    TokenKind::GreaterEqual
                }
                ('&', Some('&')) => {
                    index += 2;
                    column += 2;
                    TokenKind::AmpAmp
                }
                ('|', Some('|')) => {
                    index += 2;
                    column += 2;
                    TokenKind::PipePipe
                }
                _ => {
                    index += 1;
                    column += 1;
                    match character {
                        '+' => TokenKind::Plus,
                        '-' => TokenKind::Minus,
                        '*' => TokenKind::Star,
                        '/' => TokenKind::Slash,
                        '%' => TokenKind::Percent,
                        '=' => TokenKind::Equal,
                        '!' => TokenKind::Bang,
                        '<' => TokenKind::Less,
                        '>' => TokenKind::Greater,
                        ';' => TokenKind::Semicolon,
                        '(' => TokenKind::LeftParen,
                        ')' => TokenKind::RightParen,
                        '{' => TokenKind::LeftBrace,
                        '}' => TokenKind::RightBrace,
                        _ => {
                            return Err(CompileError::source(
                                span.line,
                                span.column,
                                format!("unexpected character '{character}'"),
                            ));
                        }
                    }
                }
            };
            kind
        };

        tokens.push(Token { kind, span });
    }

    tokens.push(Token {
        kind: TokenKind::Eof,
        span: Span { line, column },
    });
    Ok(tokens)
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Expression {
    kind: ExpressionKind,
    span: Span,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ExpressionKind {
    Integer(i64),
    Variable(String),
    Unary(UnaryOperator, Box<Expression>),
    Binary(Box<Expression>, BinaryOperator, Box<Expression>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum UnaryOperator {
    Minus,
    Not,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BinaryOperator {
    Add,
    Subtract,
    Multiply,
    Divide,
    Remainder,
    Equal,
    NotEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    And,
    Or,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Statement {
    Let {
        name: String,
        value: Expression,
        span: Span,
    },
    Assign {
        name: String,
        value: Expression,
        span: Span,
    },
    Print(Expression),
    Block(Vec<Statement>, Span),
    If {
        condition: Expression,
        then_branch: Box<Statement>,
        else_branch: Option<Box<Statement>>,
    },
    While {
        condition: Expression,
        body: Box<Statement>,
    },
    Break(Span),
    Continue(Span),
}

struct Parser {
    tokens: Vec<Token>,
    current: usize,
    loop_depth: usize,
    expression_depth: usize,
    expression_operators: usize,
    scopes: Vec<HashMap<String, Span>>,
}

impl Parser {
    fn new(tokens: Vec<Token>) -> Self {
        Self {
            tokens,
            current: 0,
            loop_depth: 0,
            expression_depth: 0,
            expression_operators: 0,
            scopes: vec![HashMap::new()],
        }
    }

    fn parse(mut self) -> Result<Vec<Statement>, CompileError> {
        let mut statements = Vec::new();
        while !self.check(TokenKind::Eof) {
            statements.push(self.statement(MAX_BLOCK_DEPTH)?);
        }
        Ok(statements)
    }

    fn statement(&mut self, depth: usize) -> Result<Statement, CompileError> {
        if depth == 0 {
            let token = self.peek();
            return Err(CompileError::source(
                token.span.line,
                token.span.column,
                "maximum block nesting depth exceeded",
            ));
        }

        if self.match_kind(TokenKind::Let) {
            let name_token = self.advance().clone();
            let name = match name_token.kind {
                TokenKind::Identifier(name) => name,
                _ => {
                    return Err(CompileError::source(
                        name_token.span.line,
                        name_token.span.column,
                        "expected a variable name after 'let'",
                    ));
                }
            };
            if self
                .scopes
                .last()
                .is_some_and(|scope| scope.contains_key(&name))
            {
                return Err(CompileError::source(
                    name_token.span.line,
                    name_token.span.column,
                    format!("'{name}' is already declared in this scope"),
                ));
            }
            self.consume(TokenKind::Equal, "expected '=' after variable name")?;
            let value = self.expression()?;
            let span = name_token.span;
            self.consume(TokenKind::Semicolon, "expected ';' after declaration")?;
            self.scopes
                .last_mut()
                .expect("parser always has a global scope")
                .insert(name.clone(), span);
            return Ok(Statement::Let { name, value, span });
        }

        if self.match_kind(TokenKind::Print) {
            let value = self.expression()?;
            self.consume(TokenKind::Semicolon, "expected ';' after print expression")?;
            return Ok(Statement::Print(value));
        }

        if self.match_kind(TokenKind::If) {
            let condition = self.expression()?;
            let then_branch = Box::new(self.statement(depth - 1)?);
            let else_branch = if self.match_kind(TokenKind::Else) {
                Some(Box::new(self.statement(depth - 1)?))
            } else {
                None
            };
            return Ok(Statement::If {
                condition,
                then_branch,
                else_branch,
            });
        }

        if self.match_kind(TokenKind::While) {
            let condition = self.expression()?;
            self.loop_depth += 1;
            let body = self.statement(depth - 1);
            self.loop_depth -= 1;
            let body = Box::new(body?);
            return Ok(Statement::While { condition, body });
        }

        if self.match_kind(TokenKind::Break) {
            let token = self.previous().clone();
            if self.loop_depth == 0 {
                return Err(CompileError::source(
                    token.span.line,
                    token.span.column,
                    "'break' is only allowed inside a loop",
                ));
            }
            self.consume(TokenKind::Semicolon, "expected ';' after 'break'")?;
            return Ok(Statement::Break(token.span));
        }

        if self.match_kind(TokenKind::Continue) {
            let token = self.previous().clone();
            if self.loop_depth == 0 {
                return Err(CompileError::source(
                    token.span.line,
                    token.span.column,
                    "'continue' is only allowed inside a loop",
                ));
            }
            self.consume(TokenKind::Semicolon, "expected ';' after 'continue'")?;
            return Ok(Statement::Continue(token.span));
        }

        if self.check(TokenKind::LeftBrace) {
            return self.block(depth);
        }

        if let TokenKind::Identifier(name) = self.peek().kind.clone() {
            let token = self.advance().clone();
            if !self
                .scopes
                .iter()
                .rev()
                .any(|scope| scope.contains_key(&name))
            {
                return Err(CompileError::source(
                    token.span.line,
                    token.span.column,
                    format!("undefined variable '{name}'"),
                ));
            }
            self.consume(TokenKind::Equal, "expected '=' after variable name")?;
            let value = self.expression()?;
            self.consume(TokenKind::Semicolon, "expected ';' after assignment")?;
            return Ok(Statement::Assign {
                name,
                value,
                span: token.span,
            });
        }

        let token = self.peek();
        Err(CompileError::source(
            token.span.line,
            token.span.column,
            "expected a declaration, assignment, print, block, if, or while statement",
        ))
    }

    fn block(&mut self, depth: usize) -> Result<Statement, CompileError> {
        let opening = self.advance().clone();
        self.scopes.push(HashMap::new());
        let mut statements = Vec::new();
        let result = loop {
            if self.check(TokenKind::Eof) {
                break Err(CompileError::source(
                    opening.span.line,
                    opening.span.column,
                    "expected '}' after block",
                ));
            }
            if self.check(TokenKind::RightBrace) {
                break Ok(());
            }
            match self.statement(depth - 1) {
                Ok(statement) => statements.push(statement),
                Err(error) => break Err(error),
            }
        };
        self.scopes.pop();
        result?;
        self.advance();
        Ok(Statement::Block(statements, opening.span))
    }

    fn expression(&mut self) -> Result<Expression, CompileError> {
        let span = self.peek().span;
        let is_root = self.expression_depth == 0;
        if is_root {
            self.expression_operators = 0;
        }
        if self.expression_depth >= MAX_EXPRESSION_DEPTH {
            return Err(CompileError::source(
                span.line,
                span.column,
                "maximum expression nesting depth exceeded",
            ));
        }

        self.expression_depth += 1;
        let result = self.or_expression();
        self.expression_depth -= 1;
        if is_root {
            self.expression_operators = 0;
        }
        result
    }

    fn count_expression_operator(&mut self, span: Span) -> Result<(), CompileError> {
        self.expression_operators += 1;
        if self.expression_operators > MAX_EXPRESSION_DEPTH {
            Err(CompileError::source(
                span.line,
                span.column,
                "maximum expression complexity exceeded",
            ))
        } else {
            Ok(())
        }
    }

    fn or_expression(&mut self) -> Result<Expression, CompileError> {
        let mut left = self.and_expression()?;
        while self.match_kind(TokenKind::PipePipe) {
            let operator = self.previous().span;
            let right = self.and_expression()?;
            left = Expression {
                kind: ExpressionKind::Binary(Box::new(left), BinaryOperator::Or, Box::new(right)),
                span: operator,
            };
        }
        Ok(left)
    }

    fn and_expression(&mut self) -> Result<Expression, CompileError> {
        let mut left = self.comparison_expression()?;
        while self.match_kind(TokenKind::AmpAmp) {
            let operator = self.previous().span;
            let right = self.comparison_expression()?;
            left = Expression {
                kind: ExpressionKind::Binary(Box::new(left), BinaryOperator::And, Box::new(right)),
                span: operator,
            };
        }
        Ok(left)
    }

    fn comparison_expression(&mut self) -> Result<Expression, CompileError> {
        let mut left = self.additive_expression()?;
        loop {
            let operator = if self.match_kind(TokenKind::EqualEqual) {
                Some(BinaryOperator::Equal)
            } else if self.match_kind(TokenKind::BangEqual) {
                Some(BinaryOperator::NotEqual)
            } else if self.match_kind(TokenKind::Less) {
                Some(BinaryOperator::Less)
            } else if self.match_kind(TokenKind::LessEqual) {
                Some(BinaryOperator::LessEqual)
            } else if self.match_kind(TokenKind::Greater) {
                Some(BinaryOperator::Greater)
            } else if self.match_kind(TokenKind::GreaterEqual) {
                Some(BinaryOperator::GreaterEqual)
            } else {
                None
            };
            let Some(operator) = operator else {
                break;
            };
            let right = self.additive_expression()?;
            left = Expression {
                span: left.span,
                kind: ExpressionKind::Binary(Box::new(left), operator, Box::new(right)),
            };
        }
        Ok(left)
    }

    fn additive_expression(&mut self) -> Result<Expression, CompileError> {
        let mut left = self.multiplicative_expression()?;
        loop {
            let operator = if self.match_kind(TokenKind::Plus) {
                Some(BinaryOperator::Add)
            } else if self.match_kind(TokenKind::Minus) {
                Some(BinaryOperator::Subtract)
            } else {
                None
            };
            let Some(operator) = operator else {
                break;
            };
            let right = self.multiplicative_expression()?;
            left = Expression {
                span: left.span,
                kind: ExpressionKind::Binary(Box::new(left), operator, Box::new(right)),
            };
        }
        Ok(left)
    }

    fn multiplicative_expression(&mut self) -> Result<Expression, CompileError> {
        let mut left = self.unary_expression()?;
        loop {
            let operator = if self.match_kind(TokenKind::Star) {
                Some(BinaryOperator::Multiply)
            } else if self.match_kind(TokenKind::Slash) {
                Some(BinaryOperator::Divide)
            } else if self.match_kind(TokenKind::Percent) {
                Some(BinaryOperator::Remainder)
            } else {
                None
            };
            let Some(operator) = operator else {
                break;
            };
            let right = self.unary_expression()?;
            left = Expression {
                span: left.span,
                kind: ExpressionKind::Binary(Box::new(left), operator, Box::new(right)),
            };
        }
        Ok(left)
    }

    fn unary_expression(&mut self) -> Result<Expression, CompileError> {
        if self.match_kind(TokenKind::Minus) {
            let operator_span = self.previous().span;
            let operand = self.unary_expression()?;
            return Ok(Expression {
                span: operator_span,
                kind: ExpressionKind::Unary(UnaryOperator::Minus, Box::new(operand)),
            });
        }
        if self.match_kind(TokenKind::Bang) {
            let operator_span = self.previous().span;
            let operand = self.unary_expression()?;
            return Ok(Expression {
                span: operator_span,
                kind: ExpressionKind::Unary(UnaryOperator::Not, Box::new(operand)),
            });
        }
        self.primary_expression()
    }

    fn primary_expression(&mut self) -> Result<Expression, CompileError> {
        if let TokenKind::Integer(value) = self.peek().kind {
            let token = self.advance().clone();
            return Ok(Expression {
                kind: ExpressionKind::Integer(value),
                span: token.span,
            });
        }
        if let TokenKind::Identifier(name) = self.peek().kind.clone() {
            let token = self.advance().clone();
            if !self
                .scopes
                .iter()
                .rev()
                .any(|scope| scope.contains_key(&name))
            {
                return Err(CompileError::source(
                    token.span.line,
                    token.span.column,
                    format!("undefined variable '{name}'"),
                ));
            }
            return Ok(Expression {
                kind: ExpressionKind::Variable(name),
                span: token.span,
            });
        }
        if self.match_kind(TokenKind::LeftParen) {
            let expression = self.expression()?;
            self.consume(TokenKind::RightParen, "expected ')' after expression")?;
            return Ok(expression);
        }

        let token = self.peek();
        Err(CompileError::source(
            token.span.line,
            token.span.column,
            "expected a number, variable, or parenthesized expression",
        ))
    }

    fn consume(&mut self, kind: TokenKind, message: &str) -> Result<Token, CompileError> {
        if self.check(kind.clone()) {
            return Ok(self.advance().clone());
        }
        let token = self.peek();
        Err(CompileError::source(
            token.span.line,
            token.span.column,
            message,
        ))
    }

    fn match_kind(&mut self, kind: TokenKind) -> bool {
        if self.check(kind) {
            self.advance();
            true
        } else {
            false
        }
    }

    fn check(&self, kind: TokenKind) -> bool {
        std::mem::discriminant(&self.peek().kind) == std::mem::discriminant(&kind)
    }

    fn advance(&mut self) -> &Token {
        let token = &self.tokens[self.current];
        if self.current < self.tokens.len() - 1 {
            self.current += 1;
        }
        token
    }

    fn previous(&self) -> &Token {
        &self.tokens[self.current - 1]
    }

    fn peek(&self) -> &Token {
        &self.tokens[self.current]
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Flow {
    None,
    Break,
    Continue,
}

struct Interpreter {
    scopes: Vec<HashMap<String, i64>>,
    output: String,
    steps: usize,
    loop_depth: usize,
}

impl Interpreter {
    fn new() -> Self {
        Self {
            scopes: vec![HashMap::new()],
            output: String::new(),
            steps: 0,
            loop_depth: 0,
        }
    }

    fn execute(mut self, statements: &[Statement]) -> Result<String, CompileError> {
        match self.execute_statements(statements, false)? {
            Flow::None => Ok(self.output),
            Flow::Break => Err(CompileError::runtime("unexpected 'break' outside loop")),
            Flow::Continue => Err(CompileError::runtime("unexpected 'continue' outside loop")),
        }
    }

    fn execute_statements(
        &mut self,
        statements: &[Statement],
        block_scope: bool,
    ) -> Result<Flow, CompileError> {
        if block_scope {
            self.scopes.push(HashMap::new());
        }

        for statement in statements {
            let flow = self.execute_statement(statement)?;
            if flow != Flow::None {
                if block_scope {
                    self.scopes.pop();
                }
                return Ok(flow);
            }
        }

        if block_scope {
            self.scopes.pop();
        }
        Ok(Flow::None)
    }

    fn execute_statement(&mut self, statement: &Statement) -> Result<Flow, CompileError> {
        self.count_step()?;
        match statement {
            Statement::Let { name, value, .. } => {
                let value = self.evaluate(value)?;
                self.scopes
                    .last_mut()
                    .expect("interpreter always has a global scope")
                    .insert(name.clone(), value);
                Ok(Flow::None)
            }
            Statement::Assign { name, value, span } => {
                let value = self.evaluate(value)?;
                let scope = self
                    .scopes
                    .iter_mut()
                    .rev()
                    .find(|scope| scope.contains_key(name))
                    .ok_or_else(|| {
                        CompileError::source(
                            span.line,
                            span.column,
                            format!("undefined variable '{name}'"),
                        )
                    })?;
                scope.insert(name.clone(), value);
                Ok(Flow::None)
            }
            Statement::Print(expression) => {
                let value = self.evaluate(expression)?;
                self.output.push_str(&value.to_string());
                self.output.push('\n');
                Ok(Flow::None)
            }
            Statement::Block(statements, _) => self.execute_statements(statements, true),
            Statement::If {
                condition,
                then_branch,
                else_branch,
            } => {
                if self.evaluate(condition)? != 0 {
                    self.execute_statement(then_branch)
                } else if let Some(else_branch) = else_branch {
                    self.execute_statement(else_branch)
                } else {
                    Ok(Flow::None)
                }
            }
            Statement::While { condition, body } => {
                self.loop_depth += 1;
                let mut flow = Flow::None;
                while self.evaluate(condition)? != 0 {
                    let body_flow = self.execute_statement(body)?;
                    match body_flow {
                        Flow::Break => {
                            flow = Flow::Break;
                            break;
                        }
                        Flow::Continue => continue,
                        Flow::None => {}
                    }
                }
                self.loop_depth -= 1;
                if flow == Flow::Break {
                    Ok(Flow::None)
                } else {
                    Ok(Flow::None)
                }
            }
            Statement::Break(_) => Ok(Flow::Break),
            Statement::Continue(_) => Ok(Flow::Continue),
        }
    }

    fn evaluate(&mut self, expression: &Expression) -> Result<i64, CompileError> {
        self.count_step()?;
        match &expression.kind {
            ExpressionKind::Integer(value) => Ok(*value),
            ExpressionKind::Variable(name) => self
                .scopes
                .iter()
                .rev()
                .find_map(|scope| scope.get(name).copied())
                .ok_or_else(|| {
                    CompileError::source(
                        expression.span.line,
                        expression.span.column,
                        format!("undefined variable '{name}'"),
                    )
                }),
            ExpressionKind::Unary(UnaryOperator::Minus, operand) => {
                let value = self.evaluate(operand)?;
                value.checked_neg().ok_or_else(|| {
                    CompileError::source(
                        expression.span.line,
                        expression.span.column,
                        "integer overflow during negation",
                    )
                })
            }
            ExpressionKind::Unary(UnaryOperator::Not, operand) => {
                let value = self.evaluate(operand)?;
                Ok(i64::from(value == 0))
            }
            ExpressionKind::Binary(left, operator, right) => match operator {
                BinaryOperator::And => {
                    let left_value = self.evaluate(left)?;
                    if left_value == 0 {
                        Ok(0)
                    } else {
                        Ok(i64::from(self.evaluate(right)? != 0))
                    }
                }
                BinaryOperator::Or => {
                    let left_value = self.evaluate(left)?;
                    if left_value != 0 {
                        Ok(1)
                    } else {
                        Ok(i64::from(self.evaluate(right)? != 0))
                    }
                }
                _ => {
                    let left_value = self.evaluate(left)?;
                    let right_value = self.evaluate(right)?;
                    match operator {
                        BinaryOperator::Add => left_value.checked_add(right_value),
                        BinaryOperator::Subtract => left_value.checked_sub(right_value),
                        BinaryOperator::Multiply => left_value.checked_mul(right_value),
                        BinaryOperator::Divide => {
                            if right_value == 0 {
                                None
                            } else {
                                left_value.checked_div(right_value)
                            }
                        }
                        BinaryOperator::Remainder => {
                            if right_value == 0 {
                                None
                            } else {
                                left_value.checked_rem(right_value)
                            }
                        }
                        BinaryOperator::Equal => {
                            return Ok(i64::from(left_value == right_value));
                        }
                        BinaryOperator::NotEqual => {
                            return Ok(i64::from(left_value != right_value));
                        }
                        BinaryOperator::Less => {
                            return Ok(i64::from(left_value < right_value));
                        }
                        BinaryOperator::LessEqual => {
                            return Ok(i64::from(left_value <= right_value));
                        }
                        BinaryOperator::Greater => {
                            return Ok(i64::from(left_value > right_value));
                        }
                        BinaryOperator::GreaterEqual => {
                            return Ok(i64::from(left_value >= right_value));
                        }
                        BinaryOperator::And | BinaryOperator::Or => unreachable!(),
                    }
                    .ok_or_else(|| {
                        let operation = match operator {
                            BinaryOperator::Add => "addition",
                            BinaryOperator::Subtract => "subtraction",
                            BinaryOperator::Multiply => "multiplication",
                            BinaryOperator::Divide => "division",
                            BinaryOperator::Remainder => "remainder",
                            _ => "arithmetic",
                        };
                        let detail = if matches!(
                            operator,
                            BinaryOperator::Divide | BinaryOperator::Remainder
                        ) && right_value == 0
                        {
                            "division by zero".to_string()
                        } else {
                            format!("integer overflow during {operation}")
                        };
                        CompileError::source(expression.span.line, expression.span.column, detail)
                    })
                }
            },
        }
    }

    fn count_step(&mut self) -> Result<(), CompileError> {
        self.steps = self.steps.saturating_add(1);
        if self.steps > MAX_EXECUTION_STEPS {
            Err(CompileError::runtime(format!(
                "execution limit exceeded ({MAX_EXECUTION_STEPS} instructions)"
            )))
        } else {
            Ok(())
        }
    }
}

/// Lexes, parses, and executes one Rusty source program.
///
/// # Examples
/// ```
/// # use pycompiler::compiler::compile_and_run;
/// let output = compile_and_run("let answer = 6 * 7; print answer;")?;
/// assert_eq!(output, "42\n");
/// # Ok::<(), pycompiler::compiler::CompileError>(())
/// ```
pub fn compile_and_run(source: &str) -> Result<String, CompileError> {
    let tokens = lex(source)?;
    let statements = Parser::new(tokens).parse()?;
    Interpreter::new().execute(&statements)
}

#[cfg(test)]
mod tests {
    use super::compile_and_run;

    fn run(source: &str) -> String {
        compile_and_run(source).expect("valid Rusty program should execute")
    }

    fn error(source: &str) -> super::CompileError {
        compile_and_run(source).expect_err("invalid Rusty program should fail")
    }

    #[test]
    fn arithmetic_and_operator_precedence() {
        assert_eq!(run("print 2 + 3 * 4; print (2 + 3) * 4;"), "14\n20\n");
    }

    #[test]
    fn remainder_and_unary_operators() {
        assert_eq!(
            run("print 17 % 5; print -(-7); print !0; print !3;"),
            "2\n7\n1\n0\n"
        );
    }

    #[test]
    fn assignment_updates_the_nearest_visible_scope() {
        assert_eq!(
            run("let x = 1; { x = 8; let y = 2; print x + y; } print x;"),
            "10\n8\n"
        );
    }

    #[test]
    fn block_can_shadow_outer_variables() {
        assert_eq!(run("let x = 1; { let x = 9; print x; } print x;"), "9\n1\n");
    }

    #[test]
    fn undefined_assignment_reports_location() {
        let diagnostic = error("let x = 1;\nx = missing;");
        assert_eq!(diagnostic.line(), Some(2));
        assert_eq!(diagnostic.column(), Some(5));
    }

    #[test]
    fn undefined_variable_in_expression_reports_location() {
        let diagnostic = error("print missing;");
        assert_eq!(diagnostic.line(), Some(1));
        assert_eq!(diagnostic.column(), Some(7));
    }

    #[test]
    fn duplicate_declarations_are_allowed_only_when_scoped() {
        assert_eq!(run("let x = 1; { let x = 2; print x; }"), "2\n");
        let diagnostic = error("let x = 1; let x = 2;");
        assert!(!diagnostic.is_runtime());
    }

    #[test]
    fn duplicate_declaration_reports_location_in_the_parser() {
        let diagnostic = error("let x = 1; let x = 2;");
        assert_eq!(diagnostic.line(), Some(1));
        assert_eq!(diagnostic.column(), Some(16));
    }

    #[test]
    fn all_comparison_operators() {
        assert_eq!(
            run(
                "print 1 == 1; print 1 != 2; print 1 < 2; print 2 <= 2; print 3 > 2; print 3 >= 3;"
            ),
            "1\n1\n1\n1\n1\n1\n"
        );
    }

    #[test]
    fn logical_operators_use_short_circuit_evaluation() {
        assert_eq!(
            run("print 0 && (1 / 0); print 1 || (1 / 0); print 3 && 4; print 0 || 4;"),
            "0\n1\n1\n1\n"
        );
    }

    #[test]
    fn if_else_and_nested_blocks() {
        assert_eq!(
            run("let x = 4; if x >= 4 { if x == 4 { print 42; } } else { print 0; }"),
            "42\n"
        );
    }

    #[test]
    fn while_loop_and_break() {
        assert_eq!(
            run("let i = 0; while i < 10 { i = i + 1; if i == 4 { break; } } print i;"),
            "4\n"
        );
    }

    #[test]
    fn while_loop_and_continue() {
        assert_eq!(
            run("let i = 0; let total = 0; while i < 5 { i = i + 1; if i == 3 { continue; } total = total + i; } print total;"),
            "12\n"
        );
    }

    #[test]
    fn break_outside_loop_is_rejected_by_parser() {
        let diagnostic = error("break;");
        assert_eq!(
            diagnostic.message(),
            "'break' is only allowed inside a loop"
        );
    }

    #[test]
    fn continue_outside_loop_is_rejected_by_parser() {
        let diagnostic = error("continue;");
        assert_eq!(
            diagnostic.message(),
            "'continue' is only allowed inside a loop"
        );
    }

    #[test]
    fn empty_program_succeeds() {
        assert_eq!(run("// comment only"), "");
    }

    #[test]
    fn comments_and_crlf_are_supported() {
        assert_eq!(run("// comment\r\nlet x = 7;\r\nprint x;"), "7\n");
    }

    #[test]
    fn missing_semicolon_reports_source_location() {
        let diagnostic = error("print 1");
        assert_eq!(diagnostic.line(), Some(1));
        assert_eq!(diagnostic.column(), Some(8));
    }

    #[test]
    fn unclosed_block_reports_opening_location() {
        let diagnostic = error("if 1 { print 2;");
        assert_eq!(diagnostic.line(), Some(1));
        assert_eq!(diagnostic.column(), Some(6));
    }

    #[test]
    fn unexpected_character_reports_location() {
        let diagnostic = error("print @;");
        assert_eq!(diagnostic.line(), Some(1));
        assert_eq!(diagnostic.column(), Some(7));
    }

    #[test]
    fn division_and_remainder_by_zero_report_source_location() {
        assert_eq!(error("print 1 / 0;").message(), "division by zero");
        assert_eq!(error("print 1 % 0;").message(), "division by zero");
    }

    #[test]
    fn integer_overflow_is_rejected() {
        let diagnostic = error("print 9223372036854775807 + 1;");
        assert!(diagnostic.message().contains("integer overflow"));
    }

    #[test]
    fn source_length_limit_is_enforced() {
        let diagnostic = error(&" ".repeat(super::MAX_SOURCE_LENGTH + 1));
        assert!(diagnostic.message().contains("source is too large"));
    }

    #[test]
    fn infinite_loop_stops_at_the_execution_limit() {
        let diagnostic = error("while 1 {}");
        assert!(diagnostic.message().contains("execution limit exceeded"));
    }
}
