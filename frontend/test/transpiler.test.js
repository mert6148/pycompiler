import assert from "node:assert/strict";
import test from "node:test";
import { Script } from "node:vm";
import { transpile } from "../src/transpiler.js";

const source = `let count = 2
let message = "item:"
while count > 0 {
  print(message, count)
  count = count - 1
}
if count == 0 and not false {
  print("done")
}`;

test("transpiles the education language into JavaScript source", () => {
  const output = transpile(source, "javascript");
  assert.match(output, /^let pc_count;\nlet pc_message;/);
  assert.match(output, /while \(\(pc_count > 0\)\)/);
  assert.match(output, /console\.log\(pc_message, pc_count\);/);
  assert.match(output, /if \(\(\(pc_count === 0\) && \(!false\)\)\)/);
  assert.doesNotThrow(() => new Script(output));
});

test("transpiles typed C++ and C# programs with variables visible outside blocks", () => {
  const cpp = transpile(`${source}\nprint("joined " + "text")`, "cpp");
  assert.match(cpp, /#include <iostream>/);
  assert.match(cpp, /std::string pc_message\{\};/);
  assert.match(cpp, /std::string\("joined "\) \+ std::string\("text"\)/);
  assert.match(cpp, /while \(pc_truthy\(\(pc_count > 0\)\)\)/);
  assert.match(cpp, /std::cout << pc_message << " " << pc_count/);

  const csharp = transpile(source, "csharp");
  assert.match(csharp, /double pc_count = 0;/);
  assert.match(csharp, /string pc_message = "";/);
  assert.match(csharp, /while \(Truthy\(\(pc_count > 0\)\)\)/);
  assert.match(csharp, /Console\.WriteLine/);
  assert.match(transpile('if "a" < "b" { print(true) }', "csharp"), /string\.CompareOrdinal\("a", "b"\) < 0/);
});

test("transpiles PHP and preserves boolean display and string concatenation", () => {
  const output = transpile('let text = "answer: "\nlet result = text + 42\nprint(result, true)', "php");
  assert.match(output, /function pc_add\(\$left, \$right\)/);
  assert.match(output, /pc_add\(\$pc_text, 42\)/);
  assert.match(output, /"True"/);
});

test("keeps Python as a supported target and rejects SQL as a transpilation target", () => {
  assert.equal(transpile("print(1)", "python"), "print(1)\n");
  assert.throws(() => transpile("print(1)", "sql"), /separate query editor/);
});

test("reports variables whose types cannot be represented by C++ or C#", () => {
  assert.throws(() => transpile('let value = 1\nvalue = "text"', "cpp"), /requires 'value' to keep one value type/);
  assert.throws(() => transpile('let value = 1\nvalue = "text"', "csharp"), /requires 'value' to keep one value type/);
  assert.throws(() => transpile('print("text" + 1)', "cpp"), /mixed string and numeric addition/);
  assert.throws(() => transpile("print(missing)", "csharp"), /undefined variable 'missing'/);
});
