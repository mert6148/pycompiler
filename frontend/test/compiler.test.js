import assert from "node:assert/strict";
import test from "node:test";
import { CompileError, compile, run, tokenize } from "../src/compiler.js";

test("tokenizer tracks source positions and skips comments", () => {
  const tokens = tokenize("# note\nlet value = 12");
  assert.deepEqual(tokens.slice(0, 4).map(({ kind, line, column }) => ({ kind, line, column })), [
    { kind: "NEWLINE", line: 1, column: 7 },
    { kind: "IDENT", line: 2, column: 1 },
    { kind: "IDENT", line: 2, column: 5 },
    { kind: "OP", line: 2, column: 11 },
  ]);
});

test("compiler preserves expression precedence and generates valid Python", () => {
  assert.equal(compile("print(2 + 3 * 4)\n"), "print((2 + (3 * 4)))\n");
  assert.equal(compile("print(-2 ** 2)"), "print((-(2 ** 2)))\n");
  assert.equal(compile('print("hello", 1.0, true)'), "print('hello', 1.0, True)\n");
});

test("program runner executes loops, branches, and multiple print values", () => {
  const source = `let count = 4
let total = 0
while count > 0 {
  total = total + count
  count = count - 1
}
if total == 10 and not false {
  print("sum:", total)
} else {
  print("wrong")
}`;
  assert.equal(run(source).output, "sum: 10\n");
  assert.equal(run(source).variables.total, 10);
});

test("program runner implements Python floor-division remainder and short-circuit behavior", () => {
  assert.equal(run("print(-5 // 2, -5 % 2, 5 % -2, true or missing)").output, "-3 1 -1 True\n");
  assert.equal(run("print()").output, "\n");
});

test("invalid characters and reserved identifiers report source locations", () => {
  assert.throws(() => compile("let x = 1\n@"), (error) => {
    assert.ok(error instanceof CompileError);
    assert.equal(error.line, 2);
    assert.equal(error.column, 1);
    return true;
  });
  assert.throws(() => compile("let class = 2"), /1:5: 'class' is reserved/);
});

test("runner stops runaway loops and reports undefined variables", () => {
  assert.throws(() => run("while true {\n  print(1)\n}", { maxSteps: 4 }), /stopped after 4 steps/);
  assert.throws(() => run("print(missing)"), /undefined variable 'missing'/);
  assert.throws(() => run("print(2 / 0)"), /division by zero/);
});
