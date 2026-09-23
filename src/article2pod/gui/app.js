/* article2pod GUI 前端逻辑 */
"use strict";

const $ = (id) => document.getElementById(id);

let OPTIONS = null;
let selectedArticle = null;   // 后端路径
let activePreset = null;
let activeTone = "natural";
let polling = null;

async function api(url, opts) {
  const r = await fetch(url, opts);
  return r.json();
}

/* ── 初始化 ─────────────────────────────── */

async function init() {
  OPTIONS = await api("/api/options");
  fillProvider();
  fillPresets();
  fillVoices();
  fillTones();
  checkEnv();
  loadHistory();
  bindUpload();
}

function fillProvider() {
  const sel = $("provider");
  sel.innerHTML = OPTIONS.providers.map((p) =>
    `<option value="${p.id}">${p.name}</option>`).join("");
  $("provider-hint").textContent = OPTIONS.providers[0].desc;
  sel.onchange = () => {
    const p = OPTIONS.providers.find((x) => x.id === sel.value);
    $("provider-hint").textContent = p ? p.desc : "";
  };
}

function fillPresets() {
  const box = $("presets");
  box.innerHTML = OPTIONS.presets.map((p) => `
    <div class="preset" data-id="${p.id}">
      <b>${p.name}</b><span>${p.desc}</span>
    </div>`).join("");
  box.querySelectorAll(".preset").forEach((el) => {
    el.onclick = () => {
      box.querySelectorAll(".preset").forEach((x) => x.classList.remove("active"));
      el.classList.add("active");
      activePreset = el.dataset.id;
      const p = OPTIONS.presets.find((x) => x.id === activePreset);
      $("host-voice").value = p.host;
      $("author-voice").value = p.author;
    };
  });
}

function fillVoices() {
  const opts = OPTIONS.voices.map((v) => {
    const cute = v.cute ? " 🎀" : "";
    return `<option value="${v.id}">${v.name}（${v.gender}）${cute} — ${v.desc}</option>`;
  }).join("");
  $("host-voice").innerHTML = opts;
  $("author-voice").innerHTML = opts;
  // 默认组合 = 知性访谈
  $("host-voice").value = "zh-CN-XiaoxiaoNeural";
  $("author-voice").value = "zh-CN-YunxiNeural";
  $("host-voice").onchange = clearPreset;
  $("author-voice").onchange = clearPreset;
}

function clearPreset() {
  $("presets").querySelectorAll(".preset").forEach((x) => x.classList.remove("active"));
  activePreset = null;
}

function fillTones() {
  const box = $("tones");
  box.innerHTML = OPTIONS.tones.map((t) =>
    `<button class="tone${t.id === "natural" ? " active" : ""}" data-id="${t.id}" title="${t.desc}">${t.name}</button>`
  ).join("");
  box.querySelectorAll(".tone").forEach((el) => {
    el.onclick = () => {
      box.querySelectorAll(".tone").forEach((x) => x.classList.remove("active"));
      el.classList.add("active");
      activeTone = el.dataset.id;
    };
  });
}

async function checkEnv() {
  const e = await api("/api/check-env");
  const chips = [
    ["ollama", e.ollama, "本地模型"],
    ["ffmpeg", e.ffmpeg, "合成"],
    ["edge-tts", e.edge_tts, "配音"],
    ["say", e.say, "兜底"],
  ];
  $("env").innerHTML = chips.map(([k, ok, label]) =>
    `<span class="chip ${ok ? "ok" : "bad"}" title="${k}">${label}</span>`).join("");
  $("generate").disabled = !e.ollama;
}

/* ── 文章选择 ───────────────────────────── */

function bindUpload() {
  const up = $("upload");
  const file = $("file");
  up.onclick = () => file.click();
  up.ondragover = (ev) => { ev.preventDefault(); up.classList.add("drag"); };
  up.ondragleave = () => up.classList.remove("drag");
  up.ondrop = (ev) => {
    ev.preventDefault();
    up.classList.remove("drag");
    if (ev.dataTransfer.files.length) uploadFile(ev.dataTransfer.files[0]);
  };
  file.onchange = () => { if (file.files.length) uploadFile(file.files[0]); };
  $("use-path").onclick = async () => {
    const p = $("path-input").value.trim();
    if (!p) return;
    const r = await api("/api/check-env"); // 顺手复用：本地路径直接交给后端校验
    if (r.ok) setArticle(p);
  };
}

async function uploadFile(f) {
  const fd = new FormData();
  fd.append("file", f);
  const r = await fetch("/api/upload", { method: "POST", body: fd }).then((x) => x.json());
  if (r.ok) {
    setArticle(r.path, r.name);
  } else {
    $("file-info").textContent = "上传失败：" + r.error;
  }
}

function setArticle(path, name) {
  selectedArticle = path;
  $("file-info").textContent = "已选择：" + (name || path.split("/").pop());
  $("generate").disabled = false;
}

/* ── 生成 ──────────────────────────────── */

async function generate() {
  if (!selectedArticle) return;
  const body = {
    path: selectedArticle,
    preset: activePreset,
    host_voice: $("host-voice").value,
    author_voice: $("author-voice").value,
    tone: activeTone,
  };
  $("result").hidden = true;
  $("logs").textContent = "";
  $("progress").hidden = false;
  $("generate").disabled = true;

  const r = await api("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) { alert(r.error || "启动失败"); $("generate").disabled = false; return; }
  poll(r.job_id);
}

function poll(jobId) {
  clearInterval(polling);
  polling = setInterval(async () => {
    const s = await api(`/api/status?job_id=${jobId}`);
    if (!s.ok) { clearInterval(polling); return; }
    $("fill").style.width = s.progress + "%";
    $("step").textContent = `${s.step}（${s.progress}%）`;
    if (s.logs && s.logs.length) {
      $("logs").textContent = s.logs.join("\n");
      $("logs").scrollTop = $("logs").scrollHeight;
    }
    if (s.done) {
      clearInterval(polling);
      $("generate").disabled = false;
      if (s.error) {
        $("step").textContent = "失败：" + s.error;
        $("logs").innerHTML = `<span class="err">${s.error}</span>`;
      } else if (s.results) {
        showResult(s.results);
        loadHistory();
      }
    }
  }, 800);
}

function showResult(stat) {
  const out = stat.out_dir;
  $("result").hidden = false;
  $("player").src = `/api/file?p=${out.split("/").pop()}/podcast.mp3`;
  const dls = $("downloads");
  dls.innerHTML = `
    <a href="/api/file?p=${out.split("/").pop()}/podcast.mp3" download>下载 mp3</a>
    <a href="/api/file?p=${out.split("/").pop()}/podcast.m4a" download>下载 m4a</a>
    <a href="/api/file?p=${out.split("/").pop()}/script.md" download>对话稿</a>`;
  $("meta").textContent =
    `${stat.turns} 轮对话 · ${stat.duration}s 音频 · 耗时 ${stat.seconds}s · 成本约 ¥${stat.cost}`;
}

/* ── 历史 ──────────────────────────────── */

async function loadHistory() {
  const r = await api("/api/history");
  if (!r.ok) return;
  const box = $("history");
  if (!r.items.length) {
    box.innerHTML = `<div class="empty">还没有成品，配置好声音点「生成播客」吧。</div>`;
    return;
  }
  box.innerHTML = r.items.map((it) => `
    <div class="item">
      <div>
        <b>${it.name}</b>
        <span style="color:var(--gray);font-size:12px;margin-left:8px">${it.duration}s · ${it.size_kb}KB · ${it.modified}</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <audio controls preload="none" src="${it.mp3}"></audio>
        <span class="links">
          <a href="${it.mp3}" download>mp3</a>
          ${it.m4a ? `<a href="${it.m4a}" download>m4a</a>` : ""}
          ${it.script ? `<a href="${it.script}" target="_blank">稿</a>` : ""}
        </span>
      </div>
    </div>`).join("");
}

init();
