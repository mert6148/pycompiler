const sample = `// 1'den 5'e kadar sayilari topla
let total = 0;
let index = 1;

while index <= 5 {
    total = total + index;
    index = index + 1;
}

if total == 15 {
    print total;
} else {
    print 0;
}
`;

const editor = document.querySelector("#editor");
const gutter = document.querySelector("#gutter");
const highlight = document.querySelector("#highlight");
const output = document.querySelector("#output");
const outputEmpty = document.querySelector("#output-empty");
const outputResult = document.querySelector("#output-result");
const resultIndicator = document.querySelector("#result-indicator");
const resultSummary = document.querySelector("#result-summary");
const runButton = document.querySelector("#run-button");
const panelStatus = document.querySelector("#panel-status");
const statusMessage = document.querySelector("#status-message");
const saveStatus = document.querySelector("#save-status");
const saveIndicator = document.querySelector("#save-indicator");
const dirtyIndicator = document.querySelector("#dirty-indicator");
const problemCount = document.querySelector("#problem-count");
const problemList = document.querySelector("#problem-list");
const problemsEmpty = document.querySelector("#problems-empty");
const versionCount = document.querySelector("#version-count");
const versionsList = document.querySelector("#versions-list");
const versionsEmpty = document.querySelector("#versions-empty");
const cursorPositions = [
  document.querySelector("#cursor-position"),
  document.querySelector("#status-cursor"),
];

const tokenPattern = /\/\/[^\n]*|\b(?:let|print|if|else|while)\b|\b\d+\b|(?:==|!=|<=|>=|[+\-*/<>])|[{}();=]/g;
let diagnosticLine = null;
let saveTimer = null;

try {
  editor.value = localStorage.getItem("rust-ide-source") ?? sample;
} catch (error) {
  editor.value = sample;
  saveStatus.textContent = `Yerel kayıt okunamadı: ${error.message}`;
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function tokenClass(token) {
  if (token.startsWith("//")) return "token-comment";
  if (/^(let|print|if|else|while)$/.test(token)) return "token-keyword";
  if (/^\d+$/.test(token)) return "token-number";
  if (/^(==|!=|<=|>=|[+\-*/<>])$/.test(token)) return "token-operator";
  return "token-punctuation";
}

function updateHighlight() {
  const source = editor.value;
  let html = "";
  let cursor = 0;

  for (const match of source.matchAll(tokenPattern)) {
    const token = match[0];
    const start = match.index;
    html += escapeHtml(source.slice(cursor, start));
    html += `<span class="${tokenClass(token)}">${escapeHtml(token)}</span>`;
    cursor = start + token.length;
  }

  highlight.innerHTML = html + escapeHtml(source.slice(cursor));
  syncScroll();
}

function updateGutter() {
  const lineCount = editor.value.split("\n").length;
  gutter.replaceChildren(...Array.from({ length: lineCount }, (_, index) => {
    const line = document.createElement("span");
    line.textContent = String(index + 1);
    if (index + 1 === diagnosticLine) line.classList.add("error-line");
    return line;
  }));
  syncScroll();
}

function syncScroll() {
  gutter.scrollTop = editor.scrollTop;
  highlight.scrollTop = editor.scrollTop;
  highlight.scrollLeft = editor.scrollLeft;
}

function updateCursor() {
  const beforeCursor = editor.value.slice(0, editor.selectionStart);
  const lines = beforeCursor.split("\n");
  const position = `Satır ${lines.length}, Sütun ${lines.at(-1).length + 1}`;
  cursorPositions.forEach((element) => { element.textContent = position; });
}

function saveSource() {
  try {
    localStorage.setItem("rust-ide-source", editor.value);
    saveStatus.textContent = "Tarayıcıya kaydedildi";
    saveIndicator.classList.add("visible");
    dirtyIndicator.classList.remove("visible");
    statusMessage.textContent = "Değişiklikler kaydedildi";
  } catch (error) {
    saveStatus.textContent = `Kaydetme hatası: ${error.message}`;
    statusMessage.textContent = "Yerel kayıt başarısız";
  }
  queueDatabaseSave();
}

function queueDatabaseSave() {
  clearTimeout(saveTimer);
  saveStatus.textContent = "SQLite yedeği hazırlanıyor...";
  saveTimer = setTimeout(() => {
    saveTimer = null;
    saveVersionToDatabase();
  }, 500);
}

async function saveVersionToDatabase(source = editor.value) {
  try {
    const response = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "text/plain; charset=utf-8" },
      body: source,
    });
    if (!response.ok) throw new Error(await response.text());
    saveStatus.textContent = "SQLite veritabanına kaydedildi";
    saveIndicator.classList.add("visible");
    dirtyIndicator.classList.remove("visible");
    await loadVersions();
    return true;
  } catch (error) {
    saveStatus.textContent = `Veritabanı yedeği başarısız: ${error.message}`;
    statusMessage.textContent = "Kod yalnızca tarayıcıya kaydedildi";
    return false;
  }
}

function setActivePanel(name) {
  document.querySelectorAll(".panel-tab").forEach((tab) => {
    const active = tab.dataset.panel === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelector("#output-panel").hidden = name !== "output";
  document.querySelector("#problems-panel").hidden = name !== "problems";
  document.querySelector("#versions-panel").hidden = name !== "versions";
}

async function loadVersions() {
  try {
    const response = await fetch("/api/versions");
    if (!response.ok) throw new Error(await response.text());
    const versions = await response.json();
    versionCount.textContent = String(versions.length);
    versionsEmpty.hidden = versions.length > 0;
    versionsList.replaceChildren();

    for (const version of versions) {
      const row = document.createElement("article");
      row.className = "version-row";
      const details = document.createElement("div");
      details.className = "version-details";
      const title = document.createElement("strong");
      title.textContent = `Sürüm #${version.id}`;
      const date = document.createElement("span");
      date.textContent = new Date(version.createdAt).toLocaleString("tr-TR");
      details.append(title, date);

      const restoreButton = document.createElement("button");
      restoreButton.className = "restore-button";
      restoreButton.type = "button";
      restoreButton.textContent = "Geri yükle";
      restoreButton.addEventListener("click", () => restoreVersion(version.id));
      row.append(details, restoreButton);
      versionsList.append(row);
    }
  } catch (error) {
    versionsEmpty.hidden = false;
    versionsEmpty.querySelector("strong").textContent = "Sürüm geçmişi açılamadı";
    versionsEmpty.querySelector("span:not(.empty-icon)").textContent = error.message;
  }
}

async function restoreVersion(versionId) {
  clearTimeout(saveTimer);
  saveTimer = null;
  if (!(await saveVersionToDatabase())) return;

  try {
    const response = await fetch("/api/restore", {
      method: "POST",
      headers: { "Content-Type": "text/plain; charset=utf-8" },
      body: String(versionId),
    });
    if (!response.ok) throw new Error(await response.text());
    editor.value = await response.text();
    editor.dispatchEvent(new Event("input"));
    setActivePanel("output");
    panelStatus.textContent = `Sürüm #${versionId} geri yüklendi`;
    statusMessage.textContent = "Önceki kod sürümü yüklendi";
  } catch (error) {
    saveStatus.textContent = `Sürüm geri yüklenemedi: ${error.message}`;
  }
}

function resetProblems() {
  diagnosticLine = null;
  problemCount.textContent = "0";
  problemCount.classList.remove("has-errors");
  problemList.replaceChildren();
  problemsEmpty.hidden = false;
  updateGutter();
}

function showProblem(message) {
  const match = message.match(/^(\d+):(\d+):\s*(.*)$/);
  const lineNumber = match ? Number(match[1]) : null;
  const columnNumber = match ? Number(match[2]) : null;
  const description = match ? match[3] : message;
  diagnosticLine = lineNumber;

  const row = document.createElement("button");
  row.type = "button";
  row.className = "problem-row";
  const mark = document.createElement("span");
  mark.className = "problem-mark";
  mark.textContent = "●";
  const text = document.createElement("span");
  text.className = "problem-text";
  const detail = document.createElement("span");
  detail.className = "problem-message";
  detail.textContent = description;
  const location = document.createElement("span");
  location.className = "problem-location";
  location.textContent = lineNumber ? `main.rusty · satır ${lineNumber}, sütun ${columnNumber}` : "Çalışma zamanı";
  text.append(detail, location);
  row.append(mark, text);

  if (lineNumber) {
    row.addEventListener("click", () => {
      const lines = editor.value.split("\n");
      const offset = lines.slice(0, lineNumber - 1).reduce((total, item) => total + item.length + 1, 0);
      editor.focus();
      editor.setSelectionRange(offset + columnNumber - 1, offset + columnNumber - 1);
      updateCursor();
    });
  }

  problemList.replaceChildren(row);
  problemsEmpty.hidden = true;
  problemCount.textContent = "1";
  problemCount.classList.add("has-errors");
  updateGutter();
}

function showResult(text, isError, elapsedMs) {
  outputEmpty.hidden = true;
  outputResult.hidden = false;
  output.textContent = text || (isError ? "Derleme başarısız." : "Program çıktısı yok.");
  output.classList.toggle("error", isError);
  resultIndicator.classList.toggle("error", isError);
  resultSummary.textContent = isError ? "DERLEME HATASI" : "PROGRAM ÇIKTISI";
  panelStatus.textContent = isError
    ? "Derleme başarısız"
    : `Tamamlandı · ${Math.max(1, Math.round(elapsedMs))} ms`;
}

async function runProgram() {
  const source = editor.value;
  runButton.disabled = true;
  clearTimeout(saveTimer);
  saveTimer = null;
  panelStatus.textContent = "Kod yedekleniyor...";
  statusMessage.textContent = "Program çalışıyor";
  outputEmpty.hidden = true;
  outputResult.hidden = false;
  output.textContent = "Program çalıştırılıyor...";
  output.classList.remove("error");

  const startedAt = performance.now();
  try {
    await saveVersionToDatabase(source);
    panelStatus.textContent = "Derleniyor...";
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "text/plain; charset=utf-8" },
      body: source,
    });
    const result = await response.text();
    const isError = !response.ok;
    showResult(result, isError, performance.now() - startedAt);

    if (isError) {
      showProblem(result);
      setActivePanel("problems");
      statusMessage.textContent = "Derleme hatası";
    } else {
      resetProblems();
      setActivePanel("output");
      statusMessage.textContent = "Program başarıyla çalıştı";
    }
  } catch (error) {
    const message = `Sunucuya bağlanılamadı: ${error.message}`;
    showResult(message, true, performance.now() - startedAt);
    showProblem(message);
    setActivePanel("problems");
    statusMessage.textContent = "Sunucu bağlantı hatası";
  } finally {
    runButton.disabled = false;
  }
}

editor.addEventListener("input", () => {
  diagnosticLine = null;
  dirtyIndicator.classList.add("visible");
  resetProblems();
  updateHighlight();
  updateCursor();
  saveSource();
  panelStatus.textContent = "Çalıştırma bekleniyor";
});
editor.addEventListener("scroll", syncScroll);
editor.addEventListener("keyup", updateCursor);
editor.addEventListener("click", updateCursor);
editor.addEventListener("keydown", (event) => {
  if (event.key === "Tab") {
    event.preventDefault();
    editor.setRangeText("    ", editor.selectionStart, editor.selectionEnd, "end");
    editor.dispatchEvent(new Event("input"));
  }

  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    runProgram();
  }

  if (event.key.toLowerCase() === "s" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    saveSource();
  }
});

document.querySelectorAll(".panel-tab").forEach((tab) => {
  tab.addEventListener("click", () => setActivePanel(tab.dataset.panel));
});
document.querySelector("#clear-output").addEventListener("click", () => {
  output.textContent = "";
  outputResult.hidden = true;
  outputEmpty.hidden = false;
  resetProblems();
  panelStatus.textContent = "Çıktı temizlendi";
  setActivePanel("output");
});
runButton.addEventListener("click", runProgram);

updateHighlight();
updateGutter();
updateCursor();
loadVersions();
queueDatabaseSave();
