const tokenPattern = /(?<space>[ \t\r]+)|(?<comment>\#[^\n]*)|(?<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|(?<string>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")|(?<identifier>[A-Za-z_]\w*)|(?<operator>\*\*|\/\/|==|!=|<=|>=|&&|\|\||[+\-*/%<>=!])|(?<punctuation>[(){};,])|(?<newline>\n)/y;

const reservedNames = new Set([
  "let", "print", "if", "else", "while", "true", "false", "and", "or", "not",
  "False", "None", "True", "async", "await", "break", "class", "continue",
  "def", "del", "elif", "except", "finally", "for", "from", "global", "import",
  "in", "is", "lambda", "nonlocal", "pass", "raise", "return", "try", "with",
  "yield",
]);

export class CompileError extends Error {
  constructor(message, line, column) {
    super(`${line}:${column}: ${message}`);
    this.name = "CompileError";
    this.line = line;
    this.column = column;
  }
}

export function tokenize(source) {
  const tokens = [];
  let position = 0;
  let line = 1;
  let column = 1;

  while (position < source.length) {
    tokenPattern.lastIndex = position;
    const match = tokenPattern.exec(source);
    if (!match) {
      throw new CompileError(`unexpected character ${JSON.stringify(source[position])}`, line, column);
    }

    const value = match[0];
    const kind = Object.keys(match.groups).find((name) => match.groups[name] !== undefined);
    if (kind === "newline") {
      tokens.push({ kind: "NEWLINE", value, line, column });
      line += 1;
      column = 1;
    } else {
      if (kind === "punctuation" && value === ";") {
        tokens.push({ kind: "NEWLINE", value, line, column });
      } else if (kind !== "space" && kind !== "comment") {
        const tokenKind = { identifier: "IDENT", operator: "OP" }[kind] ?? kind.toUpperCase();
        tokens.push({ kind: tokenKind, value, line, column });
      }
      column += value.length;
    }
    position = tokenPattern.lastIndex;
  }

  tokens.push({ kind: "EOF", value: "", line, column });
  return tokens;
}

class Parser {
  constructor(tokens) {
    this.tokens = tokens;
    this.position = 0;
  }

  parse() {
    const statements = [];
    this.skipNewlines();
    while (!this.at("EOF")) {
      statements.push(this.statement());
      this.skipNewlines();
    }
    return statements;
  }

  statement() {
    if (this.isWord("let")) {
      this.advance();
      const name = this.expectIdentifier("expected a variable name after 'let'");
      this.expectValue("=", "expected '=' after the variable name");
      const statement = { type: "Assignment", name: name.value, value: this.expression() };
      this.finishSimpleStatement();
      return statement;
    }

    if (this.isWord("print")) {
      this.advance();
      let values;
      if (this.matchValue("(")) {
        values = [];
        if (!this.checkValue(")")) {
          values.push(this.expression());
          while (this.matchValue(",")) values.push(this.expression());
        }
        this.expectValue(")", "expected ')' after the printed value");
      } else {
        values = [this.expression()];
      }
      this.finishSimpleStatement();
      return { type: "Print", values };
    }

    if (this.matchWord("if")) {
      const condition = this.expression();
      const body = this.block();
      this.skipNewlines();
      const elseBody = this.matchWord("else") ? this.block() : [];
      return { type: "If", condition, body, elseBody };
    }

    if (this.matchWord("while")) {
      const condition = this.expression();
      return { type: "While", condition, body: this.block() };
    }

    if (this.at("IDENT")) {
      const name = this.expectIdentifier("expected a variable name");
      this.expectValue("=", "expected '=' after the variable name");
      const statement = { type: "Assignment", name: name.value, value: this.expression() };
      this.finishSimpleStatement();
      return statement;
    }

    this.error("expected an assignment, print, if, or while statement");
  }

  block() {
    this.expectValue("{", "expected '{' before the block");
    const statements = [];
    this.skipNewlines();
    while (!this.at("EOF") && !this.checkValue("}")) {
      statements.push(this.statement());
      this.skipNewlines();
    }
    this.expectValue("}", "expected '}' to close the block");
    return statements;
  }

  finishSimpleStatement() {
    if (!this.at("NEWLINE") && !this.checkValue("}") && !this.at("EOF")) {
      this.error("expected the end of the statement");
    }
    this.skipNewlines();
  }

  expression() {
    return this.or();
  }

  or() {
    let expression = this.and();
    while (this.matchWord("or") || this.matchValue("||")) {
      expression = { type: "Binary", left: expression, operator: "or", right: this.and() };
    }
    return expression;
  }

  and() {
    let expression = this.not();
    while (this.matchWord("and") || this.matchValue("&&")) {
      expression = { type: "Binary", left: expression, operator: "and", right: this.not() };
    }
    return expression;
  }

  not() {
    if (this.matchWord("not")) return { type: "Unary", operator: "not", operand: this.not() };
    return this.equality();
  }

  equality() {
    let expression = this.comparison();
    while (this.matchValue("==") || this.matchValue("!=")) {
      expression = {
        type: "Binary", left: expression, operator: this.previous().value, right: this.comparison(),
      };
    }
    return expression;
  }

  comparison() {
    let expression = this.term();
    while (["<", "<=", ">", ">="].some((operator) => this.matchValue(operator))) {
      expression = {
        type: "Binary", left: expression, operator: this.previous().value, right: this.term(),
      };
    }
    return expression;
  }

  term() {
    let expression = this.factor();
    while (this.matchValue("+") || this.matchValue("-")) {
      expression = {
        type: "Binary", left: expression, operator: this.previous().value, right: this.factor(),
      };
    }
    return expression;
  }

  factor() {
    let expression = this.unary();
    while (this.matchValue("*") || this.matchValue("/") || this.matchValue("//") || this.matchValue("%")) {
      expression = {
        type: "Binary", left: expression, operator: this.previous().value, right: this.unary(),
      };
    }
    return expression;
  }

  unary() {
    if (this.matchValue("!") || this.matchValue("+") || this.matchValue("-")) {
      const operator = this.previous().value;
      return { type: "Unary", operator: operator === "!" ? "not" : operator, operand: this.unary() };
    }
    return this.power();
  }

  power() {
    let expression = this.primary();
    if (this.matchValue("**")) {
      expression = { type: "Binary", left: expression, operator: "**", right: this.unary() };
    }
    return expression;
  }

  primary() {
    if (this.match("NUMBER")) {
      const token = this.previous();
      const value = Number(token.value);
      if (!Number.isFinite(value)) this.errorAt(token, "number is outside the supported range");
      return { type: "Literal", value, isFloat: /[.eE]/.test(token.value) };
    }

    if (this.match("STRING")) {
      const token = this.previous();
      return { type: "Literal", value: decodeString(token.value, token) };
    }

    if (this.match("IDENT")) {
      const token = this.previous();
      if (token.value === "true") return { type: "Literal", value: true };
      if (token.value === "false") return { type: "Literal", value: false };
      if (reservedNames.has(token.value)) {
        this.errorAt(token, `'${token.value}' cannot be used as a value`);
      }
      return { type: "Variable", name: token.value };
    }

    if (this.matchValue("(")) {
      const expression = this.expression();
      this.expectValue(")", "expected ')' after the expression");
      return expression;
    }

    this.error("expected an expression");
  }

  expectIdentifier(message) {
    const token = this.expect("IDENT", message);
    if (reservedNames.has(token.value)) {
      this.errorAt(token, `'${token.value}' is reserved and cannot be a variable name`);
    }
    return token;
  }

  skipNewlines() {
    while (this.match("NEWLINE")) {}
  }

  isWord(value) {
    return this.at("IDENT") && this.peek().value === value;
  }

  matchWord(value) {
    if (!this.isWord(value)) return false;
    this.advance();
    return true;
  }

  matchValue(value) {
    if (!this.checkValue(value)) return false;
    this.advance();
    return true;
  }

  expectValue(value, message) {
    if (this.checkValue(value)) return this.advance();
    this.error(message);
  }

  match(kind) {
    if (!this.at(kind)) return false;
    this.advance();
    return true;
  }

  expect(kind, message) {
    if (this.at(kind)) return this.advance();
    this.error(message);
  }

  at(kind) {
    return this.peek().kind === kind;
  }

  checkValue(value) {
    return this.peek().value === value;
  }

  advance() {
    const token = this.peek();
    if (token.kind !== "EOF") this.position += 1;
    return token;
  }

  peek() {
    return this.tokens[this.position];
  }

  previous() {
    return this.tokens[this.position - 1];
  }

  error(message) {
    this.errorAt(this.peek(), message);
  }

  errorAt(token, message) {
    throw new CompileError(message, token.line, token.column);
  }
}

function decodeString(raw, token) {
  const quote = raw[0];
  const inner = raw.slice(1, -1);
  let result = "";

  for (let index = 0; index < inner.length; index += 1) {
    const character = inner[index];
    if (character !== "\\") {
      result += character;
      continue;
    }

    index += 1;
    if (index >= inner.length) break;
    const escaped = inner[index];
    const simpleEscapes = {
      "\\": "\\", "'": "'", '"': '"', a: "\x07", b: "\b", f: "\f",
      n: "\n", r: "\r", t: "\t", v: "\x0b",
    };
    if (Object.hasOwn(simpleEscapes, escaped)) {
      result += simpleEscapes[escaped];
    } else if (escaped === "x" || escaped === "u" || escaped === "U") {
      const digits = escaped === "x" ? 2 : escaped === "u" ? 4 : 8;
      const code = inner.slice(index + 1, index + 1 + digits);
      if (!new RegExp(`^[0-9a-fA-F]{${digits}}$`).test(code)) {
        throw new CompileError("invalid escape sequence in string", token.line, token.column);
      }
      const point = Number.parseInt(code, 16);
      if (point > 0x10ffff || (point >= 0xd800 && point <= 0xdfff)) {
        throw new CompileError("invalid Unicode code point in string", token.line, token.column);
      }
      result += String.fromCodePoint(point);
      index += digits;
    } else if (escaped === "\n") {
      continue;
    } else if (/[0-7]/.test(escaped)) {
      let octal = escaped;
      while (octal.length < 3 && /[0-7]/.test(inner[index + 1] ?? "")) {
        octal += inner[++index];
      }
      result += String.fromCodePoint(Number.parseInt(octal, 8));
    } else {
      result += `\\${escaped}`;
    }
  }

  if (!["'", '"'].includes(quote)) {
    throw new CompileError("invalid string literal", token.line, token.column);
  }
  return result;
}

function pythonString(value) {
  return `'${value.replaceAll("\\", "\\\\").replaceAll("'", "\\'").replaceAll("\n", "\\n").replaceAll("\r", "\\r").replaceAll("\t", "\\t")}'`;
}

function renderExpression(expression) {
  if (expression.type === "Literal") {
    if (typeof expression.value === "string") return pythonString(expression.value);
    if (typeof expression.value === "boolean") return expression.value ? "True" : "False";
    if (expression.isFloat && Number.isInteger(expression.value)) return `${expression.value}.0`;
    return String(expression.value);
  }
  if (expression.type === "Variable") return expression.name;
  if (expression.type === "Unary") {
    const separator = expression.operator === "not" ? " " : "";
    return `(${expression.operator}${separator}${renderExpression(expression.operand)})`;
  }
  return `(${renderExpression(expression.left)} ${expression.operator} ${renderExpression(expression.right)})`;
}

function renderStatements(statements, indentation = 0) {
  const lines = [];
  const prefix = "    ".repeat(indentation);

  for (const statement of statements) {
    if (statement.type === "Assignment") {
      lines.push(`${prefix}${statement.name} = ${renderExpression(statement.value)}`);
    } else if (statement.type === "Print") {
      lines.push(`${prefix}print(${statement.values.map(renderExpression).join(", ")})`);
    } else if (statement.type === "If") {
      lines.push(`${prefix}if ${renderExpression(statement.condition)}:`);
      lines.push(...(renderStatements(statement.body, indentation + 1) || [`${prefix}    pass`]));
      if (statement.elseBody.length) {
        lines.push(`${prefix}else:`);
        lines.push(...(renderStatements(statement.elseBody, indentation + 1) || [`${prefix}    pass`]));
      }
    } else if (statement.type === "While") {
      lines.push(`${prefix}while ${renderExpression(statement.condition)}:`);
      lines.push(...(renderStatements(statement.body, indentation + 1) || [`${prefix}    pass`]));
    }
  }
  return lines;
}

export function parse(source) {
  return new Parser(tokenize(source)).parse();
}

export function compile(source) {
  const python = renderStatements(parse(source)).join("\n");
  return python ? `${python}\n` : "";
}

function isTruthy(value) {
  return value !== false && value !== 0 && value !== "" && value !== null;
}

function evaluate(expression, variables) {
  if (expression.type === "Literal") return expression.value;
  if (expression.type === "Variable") {
    if (!Object.hasOwn(variables, expression.name)) {
      throw new Error(`undefined variable '${expression.name}'`);
    }
    return variables[expression.name];
  }
  if (expression.type === "Unary") {
    const value = evaluate(expression.operand, variables);
    if (expression.operator === "not") return !isTruthy(value);
    if (expression.operator === "+") return +value;
    return -value;
  }

  const left = evaluate(expression.left, variables);
  if (expression.operator === "and") return isTruthy(left) ? evaluate(expression.right, variables) : left;
  if (expression.operator === "or") return isTruthy(left) ? left : evaluate(expression.right, variables);
  const right = evaluate(expression.right, variables);

  switch (expression.operator) {
    case "+": return typeof left === "string" || typeof right === "string" ? String(left) + String(right) : left + right;
    case "-": return left - right;
    case "*": return left * right;
    case "/":
    case "//":
    case "%":
      if (right === 0) throw new Error("division by zero");
      if (expression.operator === "/") return left / right;
      if (expression.operator === "//") return Math.floor(left / right);
      return left - Math.floor(left / right) * right;
    case "**": return left ** right;
    case "==": return left === right;
    case "!=": return left !== right;
    case "<": return left < right;
    case "<=": return left <= right;
    case ">": return left > right;
    case ">=": return left >= right;
    default: throw new Error(`unsupported operator '${expression.operator}'`);
  }
}

export function run(source, { maxSteps = 100_000 } = {}) {
  const statements = parse(source);
  const variables = Object.create(null);
  const output = [];
  let steps = 0;

  function execute(block) {
    for (const statement of block) {
      steps += 1;
      if (steps > maxSteps) throw new Error(`execution stopped after ${maxSteps} steps`);

      if (statement.type === "Assignment") {
        variables[statement.name] = evaluate(statement.value, variables);
      } else if (statement.type === "Print") {
        output.push(statement.values.map((value) => formatValue(evaluate(value, variables))).join(" "));
      } else if (statement.type === "If") {
        execute(isTruthy(evaluate(statement.condition, variables)) ? statement.body : statement.elseBody);
      } else if (statement.type === "While") {
        while (isTruthy(evaluate(statement.condition, variables))) {
          steps += 1;
          if (steps > maxSteps) throw new Error(`execution stopped after ${maxSteps} steps`);
          execute(statement.body);
        }
      }
    }
  }

  execute(statements);
  return {
    output: output.length ? `${output.join("\n")}\n` : "",
    lines: output,
    variables,
    steps,
  };
}

function formatValue(value) {
  if (value === true) return "True";
  if (value === false) return "False";
  return String(value);
}
