import { CompileError, run } from "./compiler.js";
import { targets, transpile } from "./transpiler.js";
import { normalizeSource, sourceLanguages } from "./source-parser.js";
import { validateSql } from "./sql-validator.js";

const samples = {
  countdown: `# A tiny program, a real compiler
let count = 5
let total = 0

while count > 0 {
    total = total + count
    print("count:", count)
    count = count - 1
}

if total == 15 {
    print("The sum is", total)
} else {
    print("Something went wrong")
}`,
  fibonacci: `# Generate the first 10 Fibonacci numbers
let first = 0
let second = 1
let index = 0

while index < 10 {
    print(first)
    let next = first + second
    first = second
    second = next
    index = index + 1
}`,
  branches: `# Try a different score to explore each branch
let score = 87

if score >= 90 {
    print("Grade: A")
} else {
    if score >= 80 {
        print("Grade: B")
    } else {
        print("Keep practicing!")
    }
}`,
};

const sqlSample = `-- SQL is a separate query editor, not a transpilation target.
SELECT
    'PyCompiler' AS project,
    2026 AS release_year;`;

const sourceDefaults = {
  pycompiler: samples.countdown,
  python: `count = 5
total = 0
while count > 0:
    total = total + count
    print("count:", count)
    count = count - 1
if total == 15:
    print("The sum is", total)
else:
    print("Something went wrong")`,
  javascript: `let count = 5;
let total = 0;
while (count > 0) {
  total = total + count;
  console.log("count:", count);
  count = count - 1;
}
if (total == 15) {
  console.log("The sum is", total);
} else {
  console.log("Something went wrong");
}`,
  cpp: `int count = 5;
int total = 0;
while (count > 0) {
  total = total + count;
  std::cout << "count:" << count << std::endl;
  count = count - 1;
}
std::cout << total << std::endl;`,
  csharp: `int count = 5;
int total = 0;
while (count > 0) {
  total = total + count;
  Console.WriteLine(count);
  count = count - 1;
}
Console.WriteLine(total);`,
  c: `int count = 5;
int total = 0;
while (count > 0) {
  total = total + count;
  printf("count: %d\\n", count);
  count = count - 1;
}
printf("total: %d\\n", total);`,
  java: `int count = 5;
int total = 0;
while (count > 0) {
  total = total + count;
  System.out.println(count);
  count = count - 1;
}
System.out.println(total);`,
  php: `<?php
$count = 5;
$total = 0;
while ($count > 0) {
  $total = $total + $count;
  echo "count: ", $count;
  $count = $count - 1;
}
echo "total: ", $total;
?>`,
  sql: sqlSample,
  html: `<!doctype html>
<html lang="tr">
  <head><meta charset="UTF-8"><title>Örnek sayfa</title></head>
  <body><h1>Merhaba, PyCompiler!</h1></body>
</html>`,
  css: `body {
  font-family: sans-serif;
  color: #222;
}

h1 {
  color: #527a20;
}`,
};

const editor = document.querySelector("#source-editor");
const lineNumbers = document.querySelector("#line-numbers");
const sampleSelect = document.querySelector("#sample-select");
const targetSelect = document.querySelector("#target-select");
const sourceLanguageSelect = document.querySelector("#source-language-select");
const sampleLabel = document.querySelector("#sample-label");
const sourceFilename = document.querySelector("#source-filename");
const sourceKind = document.querySelector("#source-kind");
const sourceDescription = document.querySelector("#source-description");
const targetBadge = document.querySelector("#target-badge");
const outputTitle = document.querySelector("#python-tab");
const pythonCode = document.querySelector("#python-output code");
const pythonOutput = document.querySelector("#python-output");
const consoleOutput = document.querySelector("#console-output");
const consoleText = document.querySelector("#console-text");
const consoleCount = document.querySelector("#console-count");
const validationCount = document.querySelector("#validation-count");
const validationOutput = document.querySelector("#validation-output");
const validationText = document.querySelector("#validation-text");
const compileState = document.querySelector("#compile-state");
const editorStats = document.querySelector("#editor-stats");
const announcement = document.querySelector("#announcement");
const runButton = document.querySelector("#run-button");
const generateButton = document.querySelector("#generate-button");
const downloadButton = document.querySelector("#download-button");
const pythonTab = document.querySelector("#python-tab");
const consoleTab = document.querySelector("#console-tab");
const validationTab = document.querySelector("#validation-tab");
const validateButton = document.querySelector("#validate-button");
const targetNote = document.querySelector("#target-note");
const generatedNote = document.querySelector("#generated-note");
const resultExtension = document.querySelector("#result-extension");

let selectedTarget = "python";
let selectedSourceLanguage = "pycompiler";
const sourceTexts = new Map(Object.entries(sourceDefaults));

function isStandaloneSource() {
  return sourceLanguages[selectedSourceLanguage].standalone;
}

function updateEditorDetails() {
  const lines = editor.value.split("\n");
  lineNumbers.textContent = lines.map((_, index) => index + 1).join("\n");
  editorStats.textContent = `${lines.length} ${lines.length === 1 ? "line" : "lines"} · ${editor.value.length} chars`;
}

function setCompileState(kind, text) {
  compileState.className = `compile-state${kind ? ` ${kind}` : ""}`;
  compileState.replaceChildren(Object.assign(document.createElement("span"), { className: "state-dot" }));
  compileState.append(document.createTextNode(` ${text}`));
}

function selectTab(selected) {
  const showPython = selected === "python";
  const showConsole = selected === "console";
  const showValidation = selected === "validation";
  pythonTab.classList.toggle("active", showPython);
  consoleTab.classList.toggle("active", showConsole);
  validationTab.classList.toggle("active", showValidation);
  pythonTab.setAttribute("aria-selected", String(showPython));
  consoleTab.setAttribute("aria-selected", String(showConsole));
  validationTab.setAttribute("aria-selected", String(showValidation));
  pythonOutput.hidden = !showPython;
  consoleOutput.hidden = !showConsole;
  validationOutput.hidden = !showValidation;
}

function invalidateValidation() {
  validationCount.textContent = "—";
  validationText.className = "console-text";
  validationText.textContent = "Kod değişti; sonucu yenilemek için denetimi yeniden çalıştırın.";
}

function updateTargetDetails() {
  const target = targets[selectedTarget];
  const standalone = isStandaloneSource();
  const displayTarget = standalone ? targets[selectedSourceLanguage] : target;
  const sourceLanguage = sourceLanguages[selectedSourceLanguage];
  targetBadge.textContent = displayTarget.label === "C#" ? "CS" : displayTarget.label.toUpperCase();
  outputTitle.setAttribute("aria-label", `${displayTarget.label} output`);
  sourceFilename.textContent = standalone
    ? `main${sourceLanguage.extension}`
    : `main${sourceLanguage.extension}`;
  sourceKind.textContent = sourceLanguage.label.toUpperCase();
  sourceDescription.textContent = standalone
    ? `${sourceLanguage.label} dosyası · dönüştürülmez`
    : `${sourceLanguage.label} kaynak kodu`;
  generatedNote.textContent = standalone
    ? `${sourceLanguage.label} kaynağı · düzenleme ve dışa aktarma`
    : `${sourceLanguage.label} → ${target.label} kaynak kodu`;
  resultExtension.textContent = standalone ? sourceLanguage.extension : target.extension;
  targetNote.textContent = standalone
    ? `${sourceLanguage.label} ayrı bir kaynak türüdür; bu modda dönüştürme ve çalıştırma yapılmaz.`
    : "Çıktı kaynak koddur. Çalıştırma, dönüştürücüdeki AST yorumlayıcısını kullanır.";
  generateButton.textContent = selectedSourceLanguage === "sql"
    ? "Sorguyu önizle"
    : standalone ? "Kaynağı önizle" : "Kodu dönüştür";
  generateButton.disabled = false;
  runButton.disabled = standalone;
  sampleSelect.disabled = selectedSourceLanguage !== "pycompiler";
  sampleLabel.textContent = selectedSourceLanguage === "pycompiler"
    ? "ÖRNEK PROGRAM"
    : "ÖRNEK · PYCOMPILER";
  targetSelect.disabled = standalone;
  consoleTab.hidden = standalone;
  validateButton.textContent = selectedSourceLanguage === "sql"
    ? "SQL sorgusunu denetle"
    : "Kodu denetle";
  if (standalone) selectTab("python");
  updateEditorDetails();
}

function compileSource() {
  try {
    if (isStandaloneSource()) {
      pythonCode.textContent = editor.value
        || `${targets[selectedSourceLanguage].comment} ${sourceLanguages[selectedSourceLanguage].label} kaynağını yazın.`;
      setCompileState("", `${sourceLanguages[selectedSourceLanguage].label} önizleme`);
      announcement.textContent = `${sourceLanguages[selectedSourceLanguage].label} kaynağı önizlendi.`;
      return true;
    }
    pythonCode.textContent = transpile(editor.value, selectedTarget, selectedSourceLanguage)
      || `${targets[selectedTarget].comment} ${targets[selectedTarget].label} çıktısı boş.`;
    setCompileState("success", "Kod üretildi");
    announcement.textContent = `${targets[selectedTarget].label} kaynak kodu üretildi.`;
    return true;
  } catch (error) {
    pythonCode.textContent = error instanceof CompileError
      ? `// Derleme hatası · satır ${error.line}, sütun ${error.column}\n// ${error.message}`
      : `${targets[selectedTarget].comment} Dönüştürme hatası\n${targets[selectedTarget].comment} ${error.message}`;
    setCompileState("error", "Dönüştürme hatası");
    announcement.textContent = error.message;
    return false;
  }
}

function validateCurrentSource() {
  try {
    if (selectedSourceLanguage === "sql") {
      const result = validateSql(editor.value);
      validationCount.textContent = String(result.statementCount);
      validationText.className = "console-text success";
      validationText.textContent = `SQL yapısal denetimi başarılı: ${result.statementCount} ifade bulundu.\nBu denetim tam SQL ayrıştırıcısı değildir; sorgu veritabanına gönderilmedi ve çalıştırılmadı.`;
      setCompileState("success", "SQL yapısı uygun");
      announcement.textContent = "SQL sorgusu yapısal denetimden geçti; sorgu çalıştırılmadı.";
    } else if (isStandaloneSource()) {
      validationCount.textContent = "—";
      validationText.className = "console-text";
      validationText.textContent = `${sourceLanguages[selectedSourceLanguage].label} ayrı bir metin düzenleyicisidir; bu kaynak için compiler doğrulaması yapılmıyor.`;
      setCompileState("", "Compiler denetimi yok");
      announcement.textContent = validationText.textContent;
    } else {
      const generated = transpile(editor.value, selectedTarget, selectedSourceLanguage);
      validationCount.textContent = "✓";
      validationText.className = "console-text success";
      validationText.textContent = `Derleyici denetimi başarılı: ${sourceLanguages[selectedSourceLanguage].label} sözdizimi ${targets[selectedTarget].label} çıktısına dönüştürülebildi.\nÜretilen hedef kod çalıştırılmadı.${generated ? "" : "\nNot: Çıktı boş."}`;
      setCompileState("success", "Denetim başarılı");
      announcement.textContent = "Kaynak kod compiler denetiminden geçti.";
    }
  } catch (error) {
    validationCount.textContent = "!";
    validationText.className = "console-text error";
    validationText.textContent = error instanceof CompileError
      ? `Derleme hatası · satır ${error.line}, sütun ${error.column}\n${error.message}`
      : error.message;
    setCompileState("error", "Denetim hatası");
    announcement.textContent = error.message;
  }
  selectTab("validation");
}

function executeProgram() {
  if (isStandaloneSource()) return;
  try {
    const result = run(normalizeSource(editor.value, selectedSourceLanguage));
    consoleText.textContent = result.output || "Program çıktı üretmeden tamamlandı.";
    consoleCount.textContent = String(result.lines.length);
    announcement.textContent = "PyCompiler kaynak programı tarayıcıda çalıştırıldı.";
  } catch (error) {
    consoleText.textContent = `Çalışma zamanı hatası: ${error.message}`;
    consoleCount.textContent = "!";
    announcement.textContent = error.message;
  }
  selectTab("console");
}

function loadSample(name) {
  if (selectedSourceLanguage !== "pycompiler") return;
  editor.value = samples[name] ?? samples.countdown;
  sourceTexts.set(selectedSourceLanguage, editor.value);
  invalidateValidation();
  updateEditorDetails();
  compileSource();
  consoleText.textContent = selectedTarget === "sql"
    ? "SQL sorguları bu uygulamada çalıştırılmaz."
    : "Programı çalıştırdığınızda çıktı burada görünecek.";
  consoleCount.textContent = "0";
  selectTab("python");
  editor.focus();
}

function setTarget(target) {
  if (!Object.hasOwn(targets, target) || target === selectedTarget) return;
  selectedTarget = target;
  if (selectedTarget === "sql") {
    setSourceLanguage("sql");
    return;
  }
  if (selectedSourceLanguage === "sql") {
    selectedSourceLanguage = "pycompiler";
    sourceLanguageSelect.value = selectedSourceLanguage;
    editor.value = sourceTexts.get(selectedSourceLanguage);
  }
  targetSelect.value = selectedTarget;
  updateTargetDetails();
  invalidateValidation();
  compileSource();
  consoleCount.textContent = "0";
  consoleText.textContent = selectedTarget === "sql"
    ? "SQL sorguları bu uygulamada çalıştırılmaz."
    : "Programı çalıştırdığınızda çıktı burada görünecek.";
  selectTab("python");
}

function setSourceLanguage(language) {
  if (!Object.hasOwn(sourceLanguages, language) || language === selectedSourceLanguage) return;
  sourceTexts.set(selectedSourceLanguage, editor.value);
  selectedSourceLanguage = language;
  sourceLanguageSelect.value = language;
  editor.value = sourceTexts.get(language) ?? "";
  if (selectedTarget === "sql" && language !== "sql") {
    selectedTarget = "python";
    targetSelect.value = "python";
  } else if (language === "sql") {
    selectedTarget = "sql";
    targetSelect.value = "sql";
  }
  updateTargetDetails();
  invalidateValidation();
  compileSource();
  consoleCount.textContent = "0";
  consoleText.textContent = isStandaloneSource()
    ? `${sourceLanguages[language].label} kaynağı çalıştırılmaz.`
    : "Programı çalıştırdığınızda çıktı burada görünecek.";
  selectTab("python");
}

function outputFilename() {
  if (isStandaloneSource()) {
    return selectedSourceLanguage === "sql" ? "query.sql" : `main${sourceLanguages[selectedSourceLanguage].extension}`;
  }
  if (selectedTarget === "csharp") return "Program.cs";
  return `main${targets[selectedTarget].extension}`;
}

function downloadOutput() {
  if (!compileSource()) return;
  const fileType = isStandaloneSource() ? targets[selectedSourceLanguage] : targets[selectedTarget];
  const file = new Blob([pythonCode.textContent], { type: fileType.mime });
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = outputFilename();
  link.click();
  URL.revokeObjectURL(url);
  announcement.textContent = `${link.download} indirildi.`;
}

editor.addEventListener("input", () => {
  sourceTexts.set(selectedSourceLanguage, editor.value);
  invalidateValidation();
  updateEditorDetails();
  compileSource();
});

editor.addEventListener("scroll", () => {
  lineNumbers.scrollTop = editor.scrollTop;
});

editor.addEventListener("keydown", (event) => {
  if (event.key === "Tab") {
    event.preventDefault();
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    editor.setRangeText("    ", start, end, "end");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  } else if (!isStandaloneSource() && (event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    executeProgram();
  }
});

sampleSelect.addEventListener("change", () => loadSample(sampleSelect.value));
targetSelect.addEventListener("change", () => setTarget(targetSelect.value));
sourceLanguageSelect.addEventListener("change", () => setSourceLanguage(sourceLanguageSelect.value));
document.querySelector("#reset-button").addEventListener("click", () => loadSample(sampleSelect.value));
runButton.addEventListener("click", executeProgram);
generateButton.addEventListener("click", compileSource);
downloadButton.addEventListener("click", downloadOutput);
pythonTab.addEventListener("click", () => selectTab("python"));
consoleTab.addEventListener("click", () => {
  if (!isStandaloneSource()) selectTab("console");
});
validateButton.addEventListener("click", validateCurrentSource);
validationTab.addEventListener("click", () => selectTab("validation"));

editor.value = sourceTexts.get(selectedSourceLanguage);
sourceLanguageSelect.value = selectedSourceLanguage;
updateTargetDetails();
compileSource();
