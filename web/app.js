const sample = `// Rusty dilinde ilk programın
let base = 40;
let answer = base + 2;
print answer;
`;

const editor = document.querySelector("#editor");
const gutter = document.querySelector("#gutter");
const output = document.querySelector("#output");
const runButton = document.querySelector("#run-button");
const panelStatus = document.querySelector("#panel-status");
const cursorPosition = document.querySelector("#cursor-position");

editor.value = localStorage.getItem("rust-ide-source") ?? sample;

function updateGutter() {
  const lineCount = editor.value.split("\n").length;
  gutter.textContent = Array.from({ length: lineCount }, (_, index) => index + 1).join("\n");
  gutter.scrollTop = editor.scrollTop;
}

function updateCursor() {
  const beforeCursor = editor.value.slice(0, editor.selectionStart);
  const lines = beforeCursor.split("\n");
  cursorPosition.textContent = `Satır ${lines.length}, Sütun ${lines.at(-1).length + 1}`;
}

editor.addEventListener("input", () => {
  localStorage.setItem("rust-ide-source", editor.value);
  updateGutter();
  updateCursor();
  panelStatus.textContent = "Değişiklikler kaydedildi";
});
editor.addEventListener("scroll", () => { gutter.scrollTop = editor.scrollTop; });
editor.addEventListener("keyup", updateCursor);
editor.addEventListener("click", updateCursor);
editor.addEventListener("keydown", (event) => {
  if (event.key === "Tab") {
    event.preventDefault();
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    editor.setRangeText("    ", start, end, "end");
    editor.dispatchEvent(new Event("input"));
  }
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    runProgram();
  }
});

async function runProgram() {
  runButton.disabled = true;
  panelStatus.textContent = "Derleniyor...";
  output.classList.remove("error");
  output.textContent = "Program çalıştırılıyor...";

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "text/plain; charset=utf-8" },
      body: editor.value,
    });
    const result = await response.text();
    output.textContent = result || (response.ok ? "Program çıktısı yok." : "Derleme başarısız.");
    output.classList.toggle("error", !response.ok);
    panelStatus.textContent = response.ok ? "Çalıştırma tamamlandı" : "Derleme hatası";
  } catch (error) {
    output.textContent = `Sunucuya bağlanılamadı: ${error.message}`;
    output.classList.add("error");
    panelStatus.textContent = "Bağlantı hatası";
  } finally {
    runButton.disabled = false;
  }
}

runButton.addEventListener("click", runProgram);
updateGutter();
updateCursor();
