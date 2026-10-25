import assert from "node:assert/strict";
import test from "node:test";
import { normalizeSource, parseSource } from "../src/source-parser.js";
import { transpile } from "../src/transpiler.js";
import { run } from "../src/compiler.js";

const inputs = [
  ["python", `count = 2
while count > 0:
    print("count:", count)
    count = count - 1`],
  ["javascript", `let count = 2;
while (count > 0) {
  console.log("count:", count);
  count = count - 1;
}`],
  ["cpp", `int count = 2;
while (count > 0) {
  std::cout << "count:" << count << std::endl;
  count = count - 1;
}`],
  ["csharp", `int count = 2;
while (count > 0) {
  Console.WriteLine(count);
  count = count - 1;
}`],
  ["c", `int count = 2;
while (count > 0) {
  printf("count: %d\\n", count);
  count = count - 1;
}`],
  ["java", `int count = 2;
while (count > 0) {
  System.out.println(count);
  count = count - 1;
}`],
  ["php", `<?php
$count = 2;
while ($count > 0) {
  echo $count;
  $count = $count - 1;
}
?>`],
];

test("parses documented source-language subsets and transpiles them", () => {
  for (const [language, source] of inputs) {
    assert.ok(parseSource(source, language).length > 0, language);
    assert.match(transpile(source, "javascript", language), /while/);
    assert.notEqual(run(normalizeSource(source, language)).output, "", language);
  }
});

test("normalizes Python indentation and literals to the shared program AST", () => {
  const python = `total = 0
forbidden = False
if not forbidden:
    total = total + 1
else:
    total = 10`;
  const output = transpile(python, "python", "python");
  assert.match(output, /forbidden = False/);
  assert.match(output, /if \(not forbidden\):/);
  assert.match(output, /else:/);
});

test("supports wrapped C and Java entry points and formatted printf output", () => {
  const c = `#include <stdio.h>
int main() {
  int value = 7;
  printf("value=%d\\n", value);
  return 0;
}`;
  assert.match(transpile(c, "javascript", "c"), /console\.log\("value=", pc_value\)/);

  const java = `public class Main {
  public static void main(String[] args) {
    int value = 7;
    System.out.println(value);
  }
}`;
  assert.match(transpile(java, "php", "java"), /echo implode/);
});

test("keeps SQL, HTML, and CSS as standalone editor languages", () => {
  for (const language of ["sql", "html", "css"]) {
    assert.throws(() => parseSource("sample", language), /standalone editor mode/);
  }
});

test("reports unsupported source syntax rather than silently generating code", () => {
  assert.throws(() => parseSource("for (let i = 0; i < 3; i++) {}", "javascript"), /outside the supported/);
  assert.throws(() => parseSource("x = 1\n  y = 2", "python"), /indentation/);
});
