import { parse } from "./compiler.js";

export const sourceLanguages = {
  pycompiler: { label: "PyCompiler", extension: ".pc", standalone: false },
  python: { label: "Python", extension: ".py", standalone: false },
  javascript: { label: "JavaScript", extension: ".js", standalone: false },
  cpp: { label: "C++", extension: ".cpp", standalone: false },
  csharp: { label: "C#", extension: ".cs", standalone: false },
  c: { label: "C", extension: ".c", standalone: false },
  java: { label: "Java", extension: ".java", standalone: false },
  php: { label: "PHP", extension: ".php", standalone: false },
  sql: { label: "SQL", extension: ".sql", standalone: true },
  html: { label: "HTML", extension: ".html", standalone: true },
  css: { label: "CSS", extension: ".css", standalone: true },
};

export function parseSource(source, language) {
  const details = sourceLanguages[language];
  if (!details) throw new Error(`unsupported source language '${language}'`);
  if (details.standalone) {
    throw new Error(`${details.label} is a standalone editor mode and cannot be transpiled.`);
  }
  return parse(language === "pycompiler" ? source : normalizeSource(source, language));
}

export function normalizeSource(source, language) {
  if (!sourceLanguages[language] || sourceLanguages[language].standalone) {
    throw new Error(`unsupported source language '${language}' for transpilation`);
  }
  if (language === "pycompiler") return source;
  if (language === "python") return normalizePython(source);
  return normalizeCurlyLanguage(source, language);
}

function normalizePython(source) {
  const output = [];
  const blocks = [];
  const lines = source.replace(/\r\n?/g, "\n").split("\n");

  for (const rawLine of lines) {
    const line = stripLineComment(rawLine, "#").trimEnd();
    if (!line.trim()) continue;
    const indentation = rawLine.length - rawLine.trimStart().length;
    const text = line.trim();
    if (!blocks.length && indentation > 0) {
      throw new Error("unexpected indentation outside a Python block.");
    }

    if (/^else\s*:\s*$/.test(text)) {
      const current = blocks.at(-1);
      if (!current || current.type !== "if" || current.indentation !== indentation) {
        throw new Error("Python 'else:' must match an 'if' block at the same indentation.");
      }
      blocks.pop();
      output.push("} else {");
      blocks.push({ indentation, type: "else" });
      continue;
    }

    while (blocks.length && indentation <= blocks.at(-1).indentation) {
      blocks.pop();
      output.push("}");
    }

    const control = text.match(/^(if|while)\s+(.+):\s*$/);
    if (control) {
      output.push(`${control[1]} ${normalizePythonExpression(control[2])} {`);
      blocks.push({ indentation, type: control[1] });
    } else if (/^(elif|for|def|class|try|with|match)\b/.test(text)) {
      throw new Error(`Python '${text.split(/\s/)[0]}' statements are outside the supported source subset.`);
    } else {
      output.push(normalizePythonExpression(text));
    }
  }

  while (blocks.length) {
    blocks.pop();
    output.push("}");
  }
  return output.join("\n");
}

function normalizePythonExpression(text) {
  return replaceOutsideStrings(text, (segment) =>
    segment.replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false"));
}

function normalizeCurlyLanguage(source, language) {
  const output = [];
  const blocks = [];
  const lines = stripBlockComments(source).replace(/\r\n?/g, "\n").split("\n");

  for (const rawLine of lines) {
    let text = stripLineComment(rawLine, language === "php" ? "#" : "//").trim();
    if (!text) continue;
    if (language === "php") {
      text = replaceOutsideStrings(text, (segment) => segment.replace(/\$([A-Za-z_]\w*)/g, "$1"));
    }
    if (/^(#\s*include\b.*|#\s*pragma\b.*|using\s+[\w.]+;?$|<\?php|\?>)$/.test(text)) continue;
    if (/^(?:namespace\s+[\w.]+;?|package\s+[\w.]+;?)$/.test(text)) continue;
    if (/^return\s+0\s*;?$/.test(text)) continue;

    if (/^}\s*else\s*\{\s*$/.test(text)) {
      if (blocks.pop() !== "control") throw new Error("unexpected 'else' block.");
      output.push("} else {");
      blocks.push("control");
      continue;
    }
    if (/^}\s*$/.test(text)) {
      const block = blocks.pop();
      if (!block) throw new Error("unexpected closing brace.");
      if (block === "control") output.push("}");
      continue;
    }

    if (isWrapper(text, language)) {
      blocks.push("wrapper");
      continue;
    }

    const control = text.match(/^(if|while)\s*\((.*)\)\s*\{\s*$/);
    if (control) {
      output.push(`${control[1]} ${normalizeOperators(control[2])} {`);
      blocks.push("control");
      continue;
    }

    if (/^(else\s*\{\s*)$/.test(text)) {
      output.push("else {");
      blocks.push("control");
      continue;
    }
    if (/^(else\s+if|switch|for|do|try|catch|finally|return\b)/.test(text)) {
      throw new Error(`'${text.split(/\s/)[0]}' statements are outside the supported ${sourceLanguages[language].label} subset.`);
    }

    if (/^\}\s*else\b/.test(text) || (text.includes("{") && !text.endsWith("{"))) {
      throw new Error("place each block header and closing brace on its own line.");
    }

    const isControlBody = normalizePrint(text, language);
    const normalized = isControlBody ?? normalizeDeclarationOrAssignment(text, language);
    output.push(normalizeOperators(normalized));
    if (text.endsWith("{")) {
      throw new Error("only if/while blocks and standard program wrappers are supported.");
    }
  }

  if (blocks.includes("control")) throw new Error("missing closing brace in source program.");
  return output.join("\n");
}

function isWrapper(text, language) {
  if (language === "php" && /^(?:<\?php|\?>)$/.test(text)) return true;
  if (/^(?:public\s+)?class\s+[A-Za-z_]\w*\s*\{\s*$/.test(text)) return true;
  if (/^(?:public\s+)?static\s+void\s+main\s*\(.*\)\s*\{\s*$/.test(text)) return true;
  if (/^(?:(?:int|void)\s+main|int\s+w?main)\s*\([^)]*\)\s*\{\s*$/.test(text)) return true;
  if (/^(?:public\s+)?static\s+void\s+Main\s*\(.*\)\s*\{\s*$/.test(text)) return true;
  return false;
}

function normalizePrint(text, language) {
  const calls = {
    javascript: /^(?:console\.log|console\.info|console\.warn)\s*\((.*)\)\s*;?$/,
    java: /^System\.out\.println\s*\((.*)\)\s*;?$/,
    csharp: /^Console\.WriteLine\s*\((.*)\)\s*;?$/,
    php: /^echo\s+(.+);?$/,
  };
  if (language === "cpp" && /^std::cout\s*<</.test(text)) {
    const values = text.replace(/;\s*$/, "").replace(/^std::cout\s*<</, "")
      .split(/<</).map((part) => part.trim())
      .filter((part) => !/^std::(?:endl|flush)$/.test(part) && !/^["']\\n["']$/.test(part));
    if (!values.length) return "print()";
    return `print(${values.map((value) => value.replace(/^std::string\s*\(/, "(").replace(/\)$/g, ")")).join(", ")})`;
  }
  if (language === "c" && /^printf\s*\(/.test(text)) {
    const call = text.match(/^printf\s*\((.*)\)\s*;?$/);
    if (!call) throw new Error("C printf calls must fit on one line.");
    const args = splitArguments(call[1]);
    if (!args.length || !isQuoted(args[0])) throw new Error("C printf requires a string-literal format.");
    const format = decodeQuoted(args.shift());
    const values = [];
    let cursor = 0;
    const pattern = /%(%|[-+ 0#]*\d*(?:\.\d+)?[diuoxXfFeEgGcs])/g;
    for (const match of format.matchAll(pattern)) {
      const chunk = format.slice(cursor, match.index);
      if (chunk) values.push(JSON.stringify(chunk));
      if (match[1] === "%") values.push(JSON.stringify("%"));
      else {
        const value = args.shift();
        if (!value) throw new Error("C printf has fewer values than format specifiers.");
        values.push(value);
      }
      cursor = match.index + match[0].length;
    }
    const tail = format.slice(cursor).replace(/(?:\\n|\n)$/, "");
    if (tail) values.push(JSON.stringify(tail));
    if (args.length) values.push(...args);
    return `print(${values.join(", ")})`;
  }

  const expressionPattern = calls[language];
  if (expressionPattern) {
    const match = text.match(expressionPattern);
    if (match) return `print(${match[1].replace(/;\s*$/, "")})`;
  }
  return null;
}

function normalizeDeclarationOrAssignment(text, language) {
  let line = text.replace(/;\s*$/, "").trim();

  const declaration = /^(?:(?:const|let|var)\s+|(?:(?:const|static|final|unsigned|signed)\s+)*(?:int|long|short|double|float|decimal|bool|boolean|char|string|String|var|auto)\s+)([A-Za-z_]\w*)\s*=\s*(.+)$/.exec(line);
  if (declaration) return `${declaration[1]} = ${declaration[2]}`;

  if (/^[A-Za-z_]\w*\s*=/.test(line) || /^print\s*\(/.test(line)) return line;
  throw new Error(`unsupported ${sourceLanguages[language].label} statement: ${line}`);
}

function normalizeOperators(text) {
  return replaceOutsideStrings(text, (segment) =>
    segment.replace(/\btrue\b/gi, "true")
      .replace(/\bfalse\b/gi, "false"));
}

function stripLineComment(line, marker) {
  let quote = "";
  let escaped = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === quote) quote = "";
    } else if (character === "'" || character === '"') {
      quote = character;
    } else if (line.startsWith(marker, index)) {
      return line.slice(0, index);
    }
  }
  return line;
}

function stripBlockComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

function replaceOutsideStrings(text, transform) {
  const parts = text.split(/("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/g);
  return parts.map((part, index) => index % 2 ? part : transform(part)).join("");
}

function splitArguments(text) {
  const parts = [];
  let start = 0;
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === quote) quote = "";
    } else if (character === "'" || character === '"') {
      quote = character;
    } else if (character === "(") {
      depth += 1;
    } else if (character === ")") {
      depth -= 1;
    } else if (character === "," && depth === 0) {
      parts.push(text.slice(start, index).trim());
      start = index + 1;
    }
  }
  if (text.slice(start).trim()) parts.push(text.slice(start).trim());
  return parts;
}

function isQuoted(value) {
  return /^(['"]).*\1$/s.test(value.trim());
}

function decodeQuoted(value) {
  const body = value.trim().slice(1, -1);
  return body.replace(/\\n/g, "\n").replace(/\\t/g, "\t").replace(/\\r/g, "\r")
    .replace(/\\(["'\\])/g, "$1");
}
