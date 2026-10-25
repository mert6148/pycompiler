const statementStarters = new Set([
  "ALTER",
  "COMMIT",
  "CREATE",
  "DELETE",
  "DESCRIBE",
  "DROP",
  "EXPLAIN",
  "INSERT",
  "ROLLBACK",
  "SELECT",
  "SET",
  "SHOW",
  "START",
  "TRUNCATE",
  "UPDATE",
  "USE",
  "WITH",
]);

export class SqlValidationError extends Error {
  constructor(message, source, index) {
    const beforeError = source.slice(0, index);
    const line = beforeError.split("\n").length;
    const column = index - beforeError.lastIndexOf("\n");
    super(`${line}:${column}: ${message}`);
    this.name = "SqlValidationError";
    this.line = line;
    this.column = column;
  }
}

export function validateSql(source) {
  const statements = [];
  const mask = source.split("").map((character) => character === "\n" ? "\n" : " ");
  let state = "normal";
  let quoteStart = -1;
  let blockCommentStart = -1;
  let statementStart = 0;
  const parentheses = [];

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];

    if (state === "line-comment") {
      if (character === "\n") state = "normal";
      continue;
    }
    if (state === "block-comment") {
      if (character === "*" && next === "/") {
        state = "normal";
        index += 1;
      }
      continue;
    }
    if (state === "single-quote" || state === "double-quote" || state === "backtick") {
      const delimiter = state === "single-quote" ? "'" : state === "double-quote" ? '"' : "`";
      if (character === "\\" && index + 1 < source.length) {
        index += 1;
      } else if (character === delimiter && next === delimiter) {
        index += 1;
      } else if (character === delimiter) {
        state = "normal";
      }
      continue;
    }

    if (character === "-" && next === "-") {
      state = "line-comment";
      index += 1;
    } else if (character === "#") {
      state = "line-comment";
    } else if (character === "/" && next === "*") {
      state = "block-comment";
      blockCommentStart = index;
      index += 1;
    } else if (character === "'") {
      state = "single-quote";
      quoteStart = index;
      mask[index] = "x";
    } else if (character === '"') {
      state = "double-quote";
      quoteStart = index;
      mask[index] = "x";
    } else if (character === "`") {
      state = "backtick";
      quoteStart = index;
      mask[index] = "x";
    } else if (character === "(") {
      parentheses.push(index);
    } else if (character === ")") {
      if (!parentheses.length) {
        throw new SqlValidationError("Eşleşmeyen ')' parantezi.", source, index);
      }
      parentheses.pop();
    } else if (character === ";") {
      statements.push({ text: source.slice(statementStart, index), mask: mask.slice(statementStart, index).join(""), start: statementStart });
      statementStart = index + 1;
    } else {
      mask[index] = character;
    }
  }

  if (state === "single-quote" || state === "double-quote" || state === "backtick") {
    throw new SqlValidationError("Kapatılmamış tırnak veya tanımlayıcı.", source, quoteStart);
  }
  if (state === "block-comment") {
    throw new SqlValidationError("Kapatılmamış blok yorumu.", source, blockCommentStart);
  }
  if (parentheses.length) {
    throw new SqlValidationError("Kapatılmamış '(' parantezi.", source, parentheses.at(-1));
  }

  statements.push({ text: source.slice(statementStart), mask: mask.slice(statementStart).join(""), start: statementStart });
  const nonEmptyStatements = statements.filter(({ mask: statementMask }) => statementMask.trim());
  if (!nonEmptyStatements.length) {
    throw new SqlValidationError("Denetlenecek bir SQL sorgusu bulunamadı.", source, 0);
  }

  for (const statement of nonEmptyStatements) {
    validateStatement(statement, source);
  }

  return { statementCount: nonEmptyStatements.length };
}

function validateStatement({ text, mask, start }, source) {
  const trimmed = mask.trim();
  const leadingWhitespace = mask.length - mask.trimStart().length;
  const keyword = trimmed.match(/^[A-Za-z]+/)?.[0]?.toUpperCase();
  if (!keyword || !statementStarters.has(keyword)) {
    throw new SqlValidationError("Desteklenmeyen veya tanınmayan SQL ifade başlangıcı.", source, start + leadingWhitespace);
  }

  const remainder = trimmed.slice(keyword.length).trim();
  if (keyword === "SELECT" && (!remainder || /^(FROM|WHERE|GROUP|ORDER|HAVING|LIMIT)\b/i.test(remainder))) {
    throw new SqlValidationError("SELECT ifadesinde döndürülecek bir alan veya ifade bulunmalı.", source, start + leadingWhitespace);
  }
  if (keyword === "INSERT" && (!/\bINTO\b/i.test(remainder) || !/\b(VALUES|SELECT|SET)\b/i.test(remainder))) {
    throw new SqlValidationError("INSERT ifadesi INTO ve VALUES, SELECT veya SET bölümlerini içermeli.", source, start + leadingWhitespace);
  }
  if (keyword === "UPDATE" && !/\bSET\b/i.test(remainder)) {
    throw new SqlValidationError("UPDATE ifadesinde SET bölümü bulunmalı.", source, start + leadingWhitespace);
  }
  if (keyword === "DELETE" && !/^\s+FROM\b/i.test(remainder)) {
    throw new SqlValidationError("DELETE ifadesinde FROM bölümü bulunmalı.", source, start + leadingWhitespace);
  }
}
