import { makeZip } from "./zip.js";

const $ = (selector) => document.querySelector(selector);
const files = [];
let groups = [], busy = false, filter = "all", toastTimer, connected = false;
const imageInputs = ["jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "ico"];
const audioInputs = ["mp3", "wav", "flac", "ogg", "m4a", "aac", "aiff", "opus", "wma"];
const videoInputs = ["mp4", "webm", "mov", "mkv", "avi", "m4v"];

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.setAttribute("aria-hidden", "true");
  svg.append(use);
  return svg;
}
function iconButton(name, label, action) {
  const button = element("button", "icon-button");
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.append(icon(name));
  button.addEventListener("click", action);
  return button;
}
function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 5500);
}
function kindFor(name) {
  const ext = name.split(".").pop().toLowerCase();
  if (imageInputs.includes(ext)) return "image";
  if (["csv", "tsv", "json"].includes(ext)) return "data";
  if (audioInputs.includes(ext)) return "audio";
  if (videoInputs.includes(ext)) return "video";
  if (ext === "zip") return "archive";
  return "unknown";
}
function allowedGroups(kind) {
  return groups.filter(group => group.enabled && (kind === "archive" || kind === "unknown" || group.id === kind || (kind === "video" && group.id === "audio")));
}
function options(select, kind, selected) {
  select.replaceChildren();
  for (const group of allowedGroups(kind)) {
    const optgroup = element("optgroup");
    optgroup.label = group.label;
    for (const target of group.targets) {
      const option = element("option", "", target.toUpperCase());
      option.value = target;
      optgroup.append(option);
    }
    select.append(optgroup);
  }
  if (Array.from(select.options).some(option => option.value === selected)) select.value = selected;
}
function defaultFor(kind) {
  const available = allowedGroups(kind).flatMap(group => group.targets);
  const preferred = $("#default-target").value;
  return available.includes(preferred) ? preferred : available[0] || "";
}
function release(file) {
  if (file.result) URL.revokeObjectURL(file.result.url);
  file.result = null;
}
function addFiles(incoming) {
  if (busy) return toast("현재 변환이 끝난 뒤 파일을 추가하세요.");
  if (!connected) return toast("변환 엔진에 연결하지 못했습니다. 앱을 실행하고 새로고침하세요.");
  const errors = [];
  for (const input of incoming) {
    if (files.length >= 20) { errors.push("한 번에 최대 20개까지 추가할 수 있습니다."); break; }
    if (input.size > 100 * 1024 * 1024) { errors.push(`${input.name}: 100 MB를 초과합니다.`); continue; }
    if (!input.size) { errors.push(`${input.name}: 빈 파일입니다.`); continue; }
    if (files.reduce((size, file) => size + file.input.size, 0) + input.size > 500 * 1024 * 1024) {
      errors.push("선택한 파일의 전체 크기는 최대 500 MB입니다."); break;
    }
    if (files.some(file => file.input.name === input.name && file.input.size === input.size && file.input.lastModified === input.lastModified)) continue;
    const kind = kindFor(input.name), target = defaultFor(kind);
    files.push({ id: crypto.randomUUID(), input, kind, target, status: target ? "pending" : "error", message: target ? "" : "미디어 엔진을 사용할 수 없습니다.", result: null });
  }
  $("#file-input").value = "";
  render();
  if (errors.length) toast(errors.join(" "));
}
function download(result) {
  const link = element("a");
  link.href = result.url;
  link.download = result.name;
  document.body.append(link);
  link.click();
  link.remove();
}
function render() {
  const list = $("#file-list");
  list.replaceChildren();
  const shown = files.filter(file => filter === "all" || file.kind === filter);
  for (const file of shown) {
    const row = element("div", "file-row");
    const badge = element("span", `file-badge ${file.kind}`, file.input.name.includes(".") ? file.input.name.split(".").pop().slice(0, 5).toUpperCase() : "FILE");
    const details = element("div", "file-details");
    const name = element("p", "file-name", file.input.name);
    name.title = file.input.name;
    details.append(name, element("p", "file-meta", `${humanSize(file.input.size)}${file.kind === "archive" ? " · ZIP 내부 파일 일괄 처리" : ""}`));
    let message = file.message;
    if (file.status === "completed") message = `${file.result.name} · ${humanSize(file.result.blob.size)}${file.result.notes.length ? " · 안내 있음" : ""}`;
    if (message) {
      const status = element("p", `file-status ${file.status === "error" ? "error" : file.status === "converting" ? "busy loading" : ""}`, message);
      details.append(status);
    }
    const select = element("select", "row-select");
    select.setAttribute("aria-label", `${file.input.name} 출력 형식`);
    options(select, file.kind, file.target);
    select.disabled = busy || !file.target;
    select.addEventListener("change", () => {
      release(file);
      file.target = select.value;
      file.status = "pending";
      file.message = "";
      render();
    });
    const actions = element("div", "row-actions");
    if (file.result) {
      const get = iconButton("download", `${file.result.name} 다운로드`, () => download(file.result));
      actions.append(get);
      if (file.result.notes.length) actions.append(iconButton("help", `${file.input.name} 변환 안내`, () => showNotes(file)));
    }
    const remove = iconButton("close", `${file.input.name} 삭제`, () => {
      release(file);
      files.splice(files.indexOf(file), 1);
      render();
    });
    remove.disabled = busy;
    actions.append(remove);
    row.append(badge, details, select, actions);
    list.append(row);
  }
  $("#empty-state").hidden = shown.length > 0;
  $("#empty-state p").textContent = files.length && !shown.length ? "이 종류의 파일이 없어요" : "아직 추가한 파일이 없어요";
  $("#queue-count").textContent = `${files.length}개 파일`;
  $("#queue-total").textContent = files.length;
  $("#clear-all").disabled = busy || !files.length;
  $("#apply-settings").disabled = busy || !files.length;
  $("#default-target").disabled = busy || !connected;
  $("#quality").disabled = busy;
  const done = files.filter(file => file.status === "completed").length;
  const pending = files.filter(file => file.target && file.status !== "completed" && file.status !== "converting").length;
  $("#batch-summary").textContent = busy ? "파일을 변환하고 있습니다" : files.length ? `${files.length}개 파일 · ${humanSize(files.reduce((sum, file) => sum + file.input.size, 0))}` : "준비된 파일이 없습니다";
  $("#batch-detail").textContent = busy ? `${done}개 완료 · 대용량 미디어는 시간이 걸릴 수 있어요.` : done ? `${done}개 완료${pending ? ` · ${pending}개 대기 또는 재시도` : " · 결과를 다운로드하세요."}` : files.length ? "출력 형식을 확인한 뒤 모두 변환을 누르세요." : "파일을 추가해 시작하세요.";
  $("#convert-all").disabled = busy || !pending;
  $("#convert-all").replaceChildren(icon("arrows"), document.createTextNode(busy ? "변환 중…" : files.some(file => file.status === "error") ? "변환 / 재시도" : "모두 변환"));
  $("#download-bar").hidden = !done;
  $("#download-all").disabled = busy;
  $("#completed-label").textContent = `${done}개 파일 변환 완료`;
}
async function convertAll() {
  if (busy) return;
  busy = true;
  const queue = files.filter(file => file.target && file.status !== "completed");
  const quality = $("#quality").value;
  for (const file of queue) {
    file.status = "converting";
    file.message = "변환 중…";
    render();
    try {
      const query = new URLSearchParams({ filename: file.input.name, target: file.target, quality });
      const response = await fetch(`/api/convert?${query}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file.input });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(typeof error.detail === "string" ? error.detail : `변환 요청에 실패했습니다. (${response.status})`);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const encoded = disposition.match(/filename\*=UTF-8''(.+)/i)?.[1];
      const name = encoded ? decodeURIComponent(encoded) : `converted.${file.target}`;
      const notes = JSON.parse(decodeURIComponent(response.headers.get("X-Conversion-Notes") || "%5B%5D"));
      file.result = { name, blob, url: URL.createObjectURL(blob), notes };
      file.status = "completed";
      file.message = "";
    } catch (error) {
      file.status = "error";
      file.message = error instanceof TypeError ? "앱과 연결이 끊어졌습니다. 실행 상태를 확인하고 다시 시도하세요." : error.message;
    }
  }
  busy = false;
  render();
  const errors = queue.filter(file => file.status === "error").length;
  toast(errors ? `${queue.length - errors}개 완료, ${errors}개 실패. 파일별 오류를 확인하세요.` : `${queue.length}개 파일의 변환이 완료되었습니다.`);
}
function openDialog(title, nodes) {
  $("#dialog-title").textContent = title;
  $("#dialog-content").replaceChildren(...nodes);
  $("#info-dialog").showModal();
}
function showNotes(file) {
  openDialog("변환 안내", [element("p", "", file.input.name), ...file.result.notes.map(note => element("p", "", note))]);
}
function showFormats() {
  const nodes = [element("p", "", "확장자만 바꾸지 않고 파일 내용을 실제로 변환합니다. 이미지 형식은 파일 내용으로 확인합니다.")];
  for (const group of groups) {
    nodes.push(element("h3", "", `${group.label}${group.enabled ? "" : " · 엔진 설치 필요"}`));
    const chips = element("div", "format-chips");
    group.targets.forEach(target => chips.append(element("span", "", target.toUpperCase())));
    nodes.push(chips);
  }
  nodes.push(element("h3", "", "ZIP 컨테이너"), element("p", "", "선택한 출력 형식과 호환되는 내부 파일을 변환합니다. 나머지·중첩 압축 파일은 원본을 보존합니다. 최대 500개 항목·압축 해제 기준 256 MB. 암호화 ZIP은 지원하지 않습니다."), element("h3", "", "변환 전 확인"), element("p", "", "투명 이미지를 JPG/BMP로 바꾸면 배경은 흰색이 됩니다. 애니메이션·다중 페이지 이미지는 첫 프레임만 변환합니다. 이미지·미디어 메타데이터는 제거합니다. CSV/TSV/JSON은 UTF-8 표 형식만 지원합니다. PDF·오피스 문서·HEIC·RAR·7z 변환은 현재 지원하지 않습니다."));
  openDialog("지원 형식", nodes);
}
function showGuide() {
  const steps = element("ol");
  ["파일을 끌어 놓거나 ‘파일 선택’을 눌러 추가하세요. 파일당 100 MB, 최대 20개·합계 500 MB까지 가능합니다.", "파일 오른쪽에서 출력 형식을 고르세요. ZIP 파일도 원하는 내부 파일의 목표 형식을 선택합니다.", "기본 출력 형식과 품질을 정한 뒤 ‘대기 중인 파일에 적용’을 누르면 호환되는 파일에 반영됩니다. 품질은 모두 변환을 누를 때 적용됩니다.", "‘모두 변환’을 누르세요. 미디어 파일은 최대 3분간 처리하며 파일마다 완료 또는 실패 사유가 표시됩니다.", "완료한 파일은 다운로드 아이콘으로 저장하세요. ‘결과 ZIP 받기’를 누르면 완료한 파일을 한 번에 묶습니다. 안내 아이콘에서 변환 시 변경된 사항을 확인하세요."].forEach(text => steps.append(element("li", "", text)));
  openDialog("사용 가이드", [steps, element("p", "", "원본 파일을 덮어쓰지 않습니다. 파일은 외부 서버에 업로드되지 않으며, 임시 미디어 파일은 변환 종료 시 삭제됩니다. 결과는 이 탭의 메모리에 있으므로 탭을 닫거나 새로고침하기 전에 다운로드하세요.")]);
}

$("#dropzone").addEventListener("click", () => { if (!busy) $("#file-input").click(); });
$("#dropzone").addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); if (!busy) $("#file-input").click(); }
});
$("#file-input").addEventListener("change", event => addFiles(Array.from(event.target.files)));
for (const name of ["dragenter", "dragover"]) $("#dropzone").addEventListener(name, event => { event.preventDefault(); $("#dropzone").classList.add("dragging"); });
for (const name of ["dragleave", "drop"]) $("#dropzone").addEventListener(name, event => { event.preventDefault(); $("#dropzone").classList.remove("dragging"); });
$("#dropzone").addEventListener("drop", event => addFiles(Array.from(event.dataTransfer.files)));
window.addEventListener("dragover", event => event.preventDefault());
window.addEventListener("drop", event => event.preventDefault());
$("#clear-all").addEventListener("click", () => { files.forEach(release); files.length = 0; render(); });
$("#quality").addEventListener("input", event => { $("#quality-value").replaceChildren(document.createTextNode(event.target.value), element("span", "", "%")); });
$("#apply-settings").addEventListener("click", () => {
  const target = $("#default-target").value;
  let count = 0;
  for (const file of files) if (file.status !== "completed" && allowedGroups(file.kind).some(group => group.targets.includes(target))) {
    file.target = target;
    file.status = "pending";
    file.message = "";
    count++;
  }
  render();
  toast(count ? `${count}개 파일에 ${target.toUpperCase()} 형식을 적용했습니다.` : "선택한 형식과 호환되는 대기 파일이 없습니다.");
});
document.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click", () => {
  filter = button.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach(item => item.classList.toggle("selected", item === button));
  render();
}));
$("#convert-all").addEventListener("click", convertAll);
$("#download-all").addEventListener("click", async () => {
  const button = $("#download-all");
  button.disabled = true;
  try {
    const blob = await makeZip(files.filter(file => file.result).map(file => ({ name: file.result.name, blob: file.result.blob })));
    const url = URL.createObjectURL(blob);
    download({ name: "converted-files.zip", url });
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
});
$("#nav-convert").addEventListener("click", () => { $("#workbench-title").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); });
$("#nav-formats").addEventListener("click", showFormats);
$("#footer-formats").addEventListener("click", showFormats);
$("#nav-guide").addEventListener("click", showGuide);
$("#close-dialog").addEventListener("click", () => $("#info-dialog").close());
$("#info-dialog").addEventListener("click", event => { if (event.target === $("#info-dialog")) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });
window.addEventListener("beforeunload", event => { if (busy || files.some(file => file.result)) { event.preventDefault(); event.returnValue = ""; } });

async function initialize() {
  try {
    const response = await fetch("/api/formats");
    if (!response.ok) throw new Error("서버 오류");
    const capabilities = await response.json();
    groups = capabilities.groups;
    connected = true;
    options($("#default-target"), "unknown", "jpg");
    $("#connection").replaceChildren(element("i"), document.createTextNode("로컬 엔진 연결됨"));
  } catch {
    $("#connection").classList.add("offline");
    $("#connection").replaceChildren(element("i"), document.createTextNode("연결할 수 없음"));
    toast("변환 엔진에 연결하지 못했습니다. 앱을 다시 실행하고 새로고침하세요.");
  }
  render();
}
initialize();
