import { compile as compilePython, parse } from "./compiler.js";
import { parseSource } from "./source-parser.js";

export const targets = {
  python: { label: "Python", extension: ".py", mime: "text/x-python;charset=utf-8", comment: "#" },
  javascript: { label: "JavaScript", extension: ".js", mime: "text/javascript;charset=utf-8", comment: "//" },
  cpp: { label: "C++", extension: ".cpp", mime: "text/x-c++src;charset=utf-8", comment: "//" },
  csharp: { label: "C#", extension: ".cs", mime: "text/plain;charset=utf-8", comment: "//" },
  php: { label: "PHP", extension: ".php", mime: "application/x-httpd-php;charset=utf-8", comment: "//" },
  sql: { label: "SQL", extension: ".sql", mime: "application/sql;charset=utf-8", comment: "--" },
  html: { label: "HTML", extension: ".html", mime: "text/html;charset=utf-8", comment: "<!--" },
  css: { label: "CSS", extension: ".css", mime: "text/css;charset=utf-8", comment: "/*" },
};

const sourceLanguagesForTranspiler = new Set([
  "pycompiler", "python", "javascript", "cpp", "csharp", "c", "java", "php",
]);

export function transpile(source, target, sourceLanguage = "pycompiler") {
  if (!Object.hasOwn(targets, target)) {
    throw new Error(`unsupported target language '${target}'`);
  }
  if (!sourceLanguagesForTranspiler.has(sourceLanguage)) {
    throw new Error(`unsupported source language '${sourceLanguage}'`);
  }
  if (target === "sql" || target === "html" || target === "css") {
    if (target === "sql") {
      throw new Error("SQL uses a separate query editor and cannot be a transpilation target.");
    }
    throw new Error(`${targets[target].label} is an editor mode, not a transpilation target.`);
  }

  const statements = sourceLanguage === "pycompiler"
    ? parse(source)
    : parseSource(source, sourceLanguage);
  if (target === "python") {
    return sourceLanguage === "pycompiler"
      ? compilePython(source)
      : compilePythonFromStatements(statements);
  }
  const names = collectAssignments(statements);
  if (target === "javascript") return transpileJavaScript(statements, names);
  if (target === "cpp" || target === "csharp") {
    const types = inferVariableTypes(statements, names, target);
    validateExpressions(statements, names, types, target);
    return target === "cpp"
      ? transpileCpp(statements, names, types)
      : transpileCsharp(statements, names, types);
  }
  return transpilePhp(statements);
}

function compilePythonFromStatements(statements) {
  const lines = [];
  function visit(block, indentation) {
    const prefix = "    ".repeat(indentation);
    for (const statement of block) {
      if (statement.type === "Assignment") {
        lines.push(`${prefix}${statement.name} = ${pythonExpression(statement.value)}`);
      } else if (statement.type === "Print") {
        lines.push(`${prefix}print(${statement.values.map(pythonExpression).join(", ")})`);
      } else if (statement.type === "If") {
        lines.push(`${prefix}if ${pythonExpression(statement.condition)}:`);
        if (statement.body.length) visit(statement.body, indentation + 1);
        else lines.push(`${prefix}    pass`);
        if (statement.elseBody.length) {
          lines.push(`${prefix}else:`);
          visit(statement.elseBody, indentation + 1);
        }
      } else if (statement.type === "While") {
        lines.push(`${prefix}while ${pythonExpression(statement.condition)}:`);
        if (statement.body.length) visit(statement.body, indentation + 1);
        else lines.push(`${prefix}    pass`);
      }
    }
  }
  visit(statements, 0);
  return `${lines.join("\n")}${lines.length ? "\n" : ""}`;
}

function pythonExpression(expression) {
  if (expression.type === "Literal") {
    if (typeof expression.value === "string") return JSON.stringify(expression.value);
    if (typeof expression.value === "boolean") return expression.value ? "True" : "False";
    return String(expression.value);
  }
  if (expression.type === "Variable") return expression.name;
  if (expression.type === "Unary") {
    const operator = expression.operator === "not" ? "not " : expression.operator;
    return `(${operator}${pythonExpression(expression.operand)})`;
  }
  return `(${pythonExpression(expression.left)} ${expression.operator} ${pythonExpression(expression.right)})`;
}

function collectReferences(statements, references = new Set()) {
  function visit(expression) {
    if (expression.type === "Variable") references.add(expression.name);
    if (expression.type === "Unary") visit(expression.operand);
    if (expression.type === "Binary") {
      visit(expression.left);
      visit(expression.right);
    }
  }
  for (const statement of statements) {
    if (statement.type === "Assignment") visit(statement.value);
    if (statement.type === "Print") statement.values.forEach(visit);
    if (statement.type === "If") {
      visit(statement.condition);
      collectReferences(statement.body, references);
      collectReferences(statement.elseBody, references);
    }
    if (statement.type === "While") {
      visit(statement.condition);
      collectReferences(statement.body, references);
    }
  }
  return references;
}

function validateExpressions(statements, names, types, target) {
  const label = targetLabel(target);
  for (const name of collectReferences(statements)) {
    if (!names.includes(name)) {
      throw new Error(`undefined variable '${name}' cannot be represented in ${label} output.`);
    }
  }

  function validate(expression) {
    if (expression.type === "Unary") {
      const operandType = inferExpression(expression.operand, types);
      if (["+", "-"].includes(expression.operator) && operandType !== "number") {
        throw new Error(`${label} requires a numeric operand for '${expression.operator}'.`);
      }
      validate(expression.operand);
      return;
    }
    if (expression.type !== "Binary") return;

    const expressionType = inferExpression(expression, types);
    const leftType = inferExpression(expression.left, types);
    const rightType = inferExpression(expression.right, types);
    if (expression.operator === "+" && expressionType === "incompatible") {
      throw new Error(`${label} does not support mixed string and numeric addition.`);
    }
    if (["-", "*", "/", "//", "%", "**"].includes(expression.operator)
      && (leftType !== "number" || rightType !== "number")) {
      throw new Error(`${label} requires numeric operands for '${expression.operator}'.`);
    }
    if (["<", "<=", ">", ">="].includes(expression.operator)
      && (leftType !== rightType || !["number", "string"].includes(leftType))) {
      throw new Error(`${label} requires matching numeric or string operands for '${expression.operator}'.`);
    }
    if (["==", "!="].includes(expression.operator)
      && leftType && rightType && leftType !== rightType) {
      throw new Error(`${label} requires matching value types for '${expression.operator}'.`);
    }
    validate(expression.left);
    validate(expression.right);
  }

  function visit(block) {
    for (const statement of block) {
      if (statement.type === "Assignment") validate(statement.value);
      if (statement.type === "Print") statement.values.forEach(validate);
      if (statement.type === "If") {
        validate(statement.condition);
        visit(statement.body);
        visit(statement.elseBody);
      }
      if (statement.type === "While") {
        validate(statement.condition);
        visit(statement.body);
      }
    }
  }
  visit(statements);
}

function collectAssignments(statements, names = []) {
  for (const statement of statements) {
    if (statement.type === "Assignment") {
      if (!names.includes(statement.name)) names.push(statement.name);
    } else if (statement.type === "If") {
      collectAssignments(statement.body, names);
      collectAssignments(statement.elseBody, names);
    } else if (statement.type === "While") {
      collectAssignments(statement.body, names);
    }
  }
  return names;
}

function inferExpression(expression, types) {
  if (expression.type === "Literal") {
    return typeof expression.value === "string"
      ? "string"
      : typeof expression.value === "boolean" ? "bool" : "number";
  }
  if (expression.type === "Variable") return types.get(expression.name);
  if (expression.type === "Unary") {
    return expression.operator === "not" ? "bool" : inferExpression(expression.operand, types);
  }
  if (["==", "!=", "<", "<=", ">", ">=", "and", "or"].includes(expression.operator)) {
    return "bool";
  }
  const left = inferExpression(expression.left, types);
  const right = inferExpression(expression.right, types);
  if (expression.operator === "+" && (left === "string" || right === "string")) {
    return left === "string" && right === "string" ? "string" : "incompatible";
  }
  if ([left, right].includes("incompatible")) return "incompatible";
  return left === "number" && right === "number" ? "number" : undefined;
}

function inferVariableTypes(statements, names, target) {
  const assignments = [];
  function visit(block) {
    for (const statement of block) {
      if (statement.type === "Assignment") assignments.push(statement);
      if (statement.type === "If") {
        visit(statement.body);
        visit(statement.elseBody);
      }
      if (statement.type === "While") visit(statement.body);
    }
  }
  visit(statements);

  const types = new Map();
  for (let pass = 0; pass <= assignments.length; pass += 1) {
    let changed = false;
    for (const assignment of assignments) {
      const inferred = inferExpression(assignment.value, types);
      if (inferred === "incompatible") {
        throw new Error(
          `${targetLabel(target)} does not support mixed string and numeric values ` +
          `in the assignment to '${assignment.name}'.`,
        );
      }
      if (!inferred) continue;
      const previous = types.get(assignment.name);
      if (previous && previous !== inferred) {
        throw new Error(
          `${targetLabel(target)} requires '${assignment.name}' to keep one value type; ` +
          `it is assigned both ${previous} and ${inferred}.`,
        );
      }
      if (!previous) {
        types.set(assignment.name, inferred);
        changed = true;
      }
    }
    if (!changed) break;
  }

  for (const name of names) {
    if (!types.has(name)) {
      throw new Error(
        `${targetLabel(target)} could not infer a type for '${name}'. ` +
        "Assign a number, string, or boolean before using it.",
      );
    }
  }
  return types;
}

function targetLabel(target) {
  return target === "cpp" ? "C++" : "C#";
}

function cppName(name) {
  return `pc_${name}`;
}

function csharpName(name) {
  return `pc_${name}`;
}

function javascriptExpression(expression) {
  if (expression.type === "Literal") {
    if (typeof expression.value === "string") return JSON.stringify(expression.value);
    if (typeof expression.value === "boolean") return expression.value ? "true" : "false";
    return String(expression.value);
  }
  if (expression.type === "Variable") return `pc_${expression.name}`;
  if (expression.type === "Unary") {
    const operator = expression.operator === "not" ? "!" : expression.operator;
    return `(${operator}${javascriptExpression(expression.operand)})`;
  }
  const left = javascriptExpression(expression.left);
  const right = javascriptExpression(expression.right);
  if (expression.operator === "//") return `Math.floor(${left} / ${right})`;
  if (expression.operator === "%") return `(((${left} % ${right}) + ${right}) % ${right})`;
  if (expression.operator === "==") return `(${left} === ${right})`;
  if (expression.operator === "!=") return `(${left} !== ${right})`;
  const operator = { and: "&&", or: "||" }[expression.operator] ?? expression.operator;
  return `(${left} ${operator} ${right})`;
}

function renderLines(
  statements,
  expression,
  assignment,
  print,
  indentation = 1,
  conditionExpression = expression,
) {
  const lines = [];
  const prefix = "    ".repeat(indentation);
  for (const statement of statements) {
    if (statement.type === "Assignment") {
      lines.push(`${prefix}${assignment(statement, expression)};`);
    } else if (statement.type === "Print") {
      lines.push(`${prefix}${print(statement, expression)}`);
    } else if (statement.type === "If") {
      lines.push(`${prefix}if (${conditionExpression(statement.condition)}) {`);
      lines.push(...(renderLines(
        statement.body, expression, assignment, print, indentation + 1, conditionExpression,
      ) || [
        `${"    ".repeat(indentation + 1)}/* empty block */`,
      ]));
      if (statement.elseBody.length) {
        lines.push(`${prefix}} else {`);
        lines.push(...(renderLines(
          statement.elseBody, expression, assignment, print, indentation + 1, conditionExpression,
        ) || [
          `${"    ".repeat(indentation + 1)}/* empty block */`,
        ]));
      }
      lines.push(`${prefix}}`);
    } else if (statement.type === "While") {
      lines.push(`${prefix}while (${conditionExpression(statement.condition)}) {`);
      lines.push(...(renderLines(
        statement.body, expression, assignment, print, indentation + 1, conditionExpression,
      ) || [
        `${"    ".repeat(indentation + 1)}/* empty block */`,
      ]));
      lines.push(`${prefix}}`);
    }
  }
  return lines;
}

function transpileJavaScript(statements, names) {
  const declarations = names.map((name) => `let pc_${name};`);
  const body = renderLines(
    statements,
    javascriptExpression,
    (statement, expression) => `pc_${statement.name} = ${expression(statement.value)}`,
    (statement, expression) =>
      `console.log(${statement.values.map(expression).join(", ")});`,
  );
  return [...declarations, ...(declarations.length && body.length ? [""] : []), ...body].join("\n")
    + (declarations.length || body.length ? "\n" : "");
}

function cppExpression(expression) {
  if (expression.type === "Literal") {
    if (typeof expression.value === "string") return `std::string(${cppString(expression.value)})`;
    if (typeof expression.value === "boolean") return expression.value ? "true" : "false";
    return String(expression.value);
  }
  if (expression.type === "Variable") return cppName(expression.name);
  if (expression.type === "Unary") {
    if (expression.operator === "not") return `(!pc_truthy(${cppExpression(expression.operand)}))`;
    const operator = expression.operator === "not" ? "!" : expression.operator;
    return `(${operator}${cppExpression(expression.operand)})`;
  }
  const left = cppExpression(expression.left);
  const right = cppExpression(expression.right);
  if (expression.operator === "**") return `std::pow(${left}, ${right})`;
  if (expression.operator === "//") return `std::floor(${left} / ${right})`;
  if (expression.operator === "%") return `(${left} - std::floor(${left} / ${right}) * ${right})`;
  if (expression.operator === "and") return `(pc_truthy(${left}) && pc_truthy(${right}))`;
  if (expression.operator === "or") return `(pc_truthy(${left}) || pc_truthy(${right}))`;
  const operator = { and: "&&", or: "||" }[expression.operator] ?? expression.operator;
  return `(${left} ${operator} ${right})`;
}

function cppString(value) {
  return JSON.stringify(value).replace(/\u2028|\u2029/g, (character) =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

function transpileCpp(statements, names, types) {
  const declarations = names.map((name) => {
    const type = types.get(name);
    const cppType = { number: "double", bool: "bool", string: "std::string" }[type];
    return `    ${cppType} ${cppName(name)}{};`;
  });
  const body = renderLines(
    statements,
    cppExpression,
    (statement, expression) => `${cppName(statement.name)} = ${expression(statement.value)}`,
    (statement, expression) => statement.values.length
      ? `std::cout << ${statement.values.map(expression).join(' << " " << ')} << '\\n';`
      : "std::cout << '\\n';",
    1,
    (condition) => `pc_truthy(${cppExpression(condition)})`,
  );
  const lines = [
    "#include <cmath>",
    "#include <iostream>",
    "#include <string>",
    "",
    "bool pc_truthy(bool value) { return value; }",
    "bool pc_truthy(double value) { return value != 0.0; }",
    "bool pc_truthy(const std::string& value) { return !value.empty(); }",
    "",
    "int main() {",
    "    std::cout << std::boolalpha;",
    ...declarations,
    ...(declarations.length && body.length ? [""] : []),
    ...body,
    "    return 0;",
    "}",
  ];
  return `${lines.join("\n")}\n`;
}

function csharpExpression(expression, types) {
  if (expression.type === "Literal") {
    if (typeof expression.value === "string") return JSON.stringify(expression.value);
    if (typeof expression.value === "boolean") return expression.value ? "true" : "false";
    return String(expression.value);
  }
  if (expression.type === "Variable") return csharpName(expression.name);
  if (expression.type === "Unary") {
    if (expression.operator === "not") {
      return `(!Truthy(${csharpExpression(expression.operand, types)}))`;
    }
    const operator = expression.operator === "not" ? "!" : expression.operator;
    return `(${operator}${csharpExpression(expression.operand, types)})`;
  }
  const left = csharpExpression(expression.left, types);
  const right = csharpExpression(expression.right, types);
  if (expression.operator === "**") return `Math.Pow(${left}, ${right})`;
  if (expression.operator === "//") return `Math.Floor(${left} / ${right})`;
  if (expression.operator === "%") return `(${left} - Math.Floor(${left} / ${right}) * ${right})`;
  if (
    ["<", "<=", ">", ">="].includes(expression.operator)
    && inferExpression(expression.left, types) === "string"
  ) return `string.CompareOrdinal(${left}, ${right}) ${expression.operator} 0`;
  if (expression.operator === "and") return `(Truthy(${left}) && Truthy(${right}))`;
  if (expression.operator === "or") return `(Truthy(${left}) || Truthy(${right}))`;
  const operator = { and: "&&", or: "||" }[expression.operator] ?? expression.operator;
  return `(${left} ${operator} ${right})`;
}

function transpileCsharp(statements, names, types) {
  const declarations = names.map((name) => {
    const type = types.get(name);
    const csharpType = { number: "double", bool: "bool", string: "string" }[type];
    const initialValue = { number: "0", bool: "false", string: '""' }[type];
    return `        ${csharpType} pc_${name} = ${initialValue};`;
  });
  const body = renderLines(
    statements,
    (expression) => csharpExpression(expression, types),
    (statement, expression) => `pc_${statement.name} = ${expression(statement.value)}`,
    (statement, expression) =>
      `Console.WriteLine(string.Join(" ", new object[] { ${statement.values.map(expression).join(", ")} }));`,
    2,
    (condition) => `Truthy(${csharpExpression(condition, types)})`,
  );
  const lines = [
    "using System;",
    "",
    "internal static class Program",
    "{",
    "    private static bool Truthy(bool value) => value;",
    "    private static bool Truthy(double value) => value != 0;",
    "    private static bool Truthy(string value) => !string.IsNullOrEmpty(value);",
    "",
    "    private static void Main()",
    "    {",
    ...declarations,
    ...(declarations.length && body.length ? [""] : []),
    ...body,
    "    }",
    "}",
  ];
  return `${lines.join("\n")}\n`;
}

function phpExpression(expression) {
  if (expression.type === "Literal") {
    if (typeof expression.value === "string") return phpString(expression.value);
    if (typeof expression.value === "boolean") return expression.value ? "true" : "false";
    return String(expression.value);
  }
  if (expression.type === "Variable") return `$pc_${expression.name}`;
  if (expression.type === "Unary") {
    const operator = expression.operator === "not" ? "!" : expression.operator;
    return `(${operator}${phpExpression(expression.operand)})`;
  }
  const left = phpExpression(expression.left);
  const right = phpExpression(expression.right);
  if (expression.operator === "**") return `(${left} ** ${right})`;
  if (expression.operator === "//") return `floor(${left} / ${right})`;
  if (expression.operator === "%") return `fmod(${left} - floor(${left} / ${right}) * ${right}, ${right})`;
  if (expression.operator === "+") return `pc_add(${left}, ${right})`;
  const operator = { and: "&&", or: "||" }[expression.operator] ?? expression.operator;
  return `(${left} ${operator} ${right})`;
}

function transpilePhp(statements) {
  const body = renderLines(
    statements,
    phpExpression,
    (statement, expression) => `$pc_${statement.name} = ${expression(statement.value)}`,
    (statement, expression) => statement.values.length
      ? `echo implode(" ", array_map("pc_string", [${statement.values.map(expression).join(", ")}])) . PHP_EOL;`
      : "echo PHP_EOL;",
    1,
  );
  const lines = [
    "<?php",
    "",
    "function pc_add($left, $right)",
    "{",
    '    if (is_string($left) || is_string($right)) return pc_string($left) . pc_string($right);',
    "    return $left + $right;",
    "}",
    "",
    "function pc_string($value): string",
    "{",
    '    if (is_bool($value)) return $value ? "True" : "False";',
    "    return (string) $value;",
    "}",
    "",
    ...body,
  ];
  return `${lines.join("\n")}\n`;
}

function phpString(value) {
  return `'${value.replaceAll("\\", "\\\\").replaceAll("'", "\\'")}'`;
}
