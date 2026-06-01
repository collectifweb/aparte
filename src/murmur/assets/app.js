"use strict";

const $ = (sel) => document.querySelector(sel);
const editor = $("#editor");
const statusEl = $("#status");
const recordBtn = $("#record");
const heroSub = $("#hero-sub");
let recordingSession = null;

function status(message) { statusEl.textContent = message || ""; }

async function postJson(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function setRecordState(state) {
  recordBtn.classList.remove("recording", "processing");
  const label = recordBtn.querySelector(".record-label");
  if (state === "recording") {
    recordBtn.classList.add("recording");
    label.textContent = "Arrêter";
    recordBtn.setAttribute("aria-label", "Arrêter la dictée");
  } else if (state === "processing") {
    recordBtn.classList.add("processing");
    label.textContent = "…";
    recordBtn.setAttribute("aria-label", "Transcription en cours");
  } else {
    label.textContent = "Parler";
    recordBtn.setAttribute("aria-label", "Démarrer la dictée");
  }
}

/* ---------- Transcription ---------- */
async function transcribeBlob(blob) {
  const model = $("#model").value;
  setRecordState("processing");
  status(`Transcription (${model})…`);
  try {
    const res = await fetch("/api/transcribe?model=" + encodeURIComponent(model), {
      method: "POST",
      headers: { "Content-Type": blob.type || "application/octet-stream" },
      body: blob,
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    editor.value = data.text;
    if ($("#autoPolish").checked && data.text.trim()) {
      await polishEditor();
    } else {
      status(data.text.trim() ? "Transcription prête." : "Aucune parole détectée.");
    }
  } finally {
    setRecordState("idle");
  }
}

async function polishEditor() {
  status("Mise en forme…");
  const data = await postJson("/api/polish", { text: editor.value });
  editor.value = data.text;
  status("Mis en forme.");
}

/* ---------- Browser WAV recording ---------- */
async function startWavRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const audioContext = new AudioContext();
  const source = audioContext.createMediaStreamSource(stream);
  const processor = audioContext.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  processor.onaudioprocess = (event) => {
    chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
  };
  source.connect(processor);
  processor.connect(audioContext.destination);
  const sampleRate = audioContext.sampleRate;
  return {
    async stop() {
      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      await audioContext.close();
      return encodeWav(chunks, sampleRate);
    },
  };
}

function encodeWav(chunks, sampleRate) {
  const total = chunks.reduce((s, c) => s + c.length, 0);
  const pcm = new Int16Array(total);
  let o = 0;
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++) {
      const s = Math.max(-1, Math.min(1, chunk[i]));
      pcm[o++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
  }
  const buffer = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(buffer);
  const ascii = (off, str) => { for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i)); };
  ascii(0, "RIFF");
  view.setUint32(4, 36 + pcm.length * 2, true);
  ascii(8, "WAVE"); ascii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, pcm.length * 2, true);
  let b = 44;
  for (let i = 0; i < pcm.length; i++, b += 2) view.setInt16(b, pcm[i], true);
  return new Blob([view], { type: "audio/wav" });
}

/* ---------- Record button ---------- */
recordBtn.addEventListener("click", async () => {
  if (recordBtn.classList.contains("processing")) return;
  if (recordingSession) {
    const session = recordingSession;
    recordingSession = null;
    const blob = await session.stop();
    try { await transcribeBlob(blob); } catch (err) { status(String(err)); setRecordState("idle"); }
    return;
  }
  try {
    recordingSession = await startWavRecording();
    setRecordState("recording");
    status("Enregistrement… appuie de nouveau pour arrêter.");
  } catch (err) {
    recordingSession = null;
    status("Micro indisponible : " + err);
  }
});

/* ---------- Action chips ---------- */
$("#polish").addEventListener("click", async () => {
  try { await polishEditor(); } catch (err) { status(String(err)); }
});
$("#pick-file").addEventListener("click", () => $("#file").click());
$("#file").addEventListener("change", async () => {
  const file = $("#file").files[0];
  if (!file) return;
  try { await transcribeBlob(file); } catch (err) { status(String(err)); setRecordState("idle"); }
});
$("#copy").addEventListener("click", async () => {
  status("Copie…");
  try {
    await postJson("/api/copy", { text: editor.value });
    status("Copié.");
  } catch (err) {
    try { await navigator.clipboard.writeText(editor.value); status("Copié (navigateur)."); }
    catch (_) { status(String(err)); }
  }
});
$("#paste").addEventListener("click", async () => {
  status("Collage…");
  try { await postJson("/api/paste", { text: editor.value }); status("Collé."); }
  catch (err) { status(String(err)); }
});

/* ---------- Drawers ---------- */
function openOverlay(id) { $(id).hidden = false; }
function closeOverlay(el) { el.hidden = true; }
document.querySelectorAll("[data-close]").forEach((b) =>
  b.addEventListener("click", (e) => closeOverlay(e.target.closest(".overlay")))
);
document.querySelectorAll(".overlay").forEach((ov) =>
  ov.addEventListener("click", (e) => { if (e.target === ov) closeOverlay(ov); })
);

/* ---------- Settings ---------- */
let allowedModels = ["small", "base"];

function kvToText(obj) {
  return Object.entries(obj || {}).map(([k, v]) => `${k} = ${v}`).join("\n");
}
function textToKv(text) {
  const out = {};
  for (const line of (text || "").split("\n")) {
    const i = line.indexOf("=");
    if (i === -1) continue;
    const k = line.slice(0, i).trim();
    if (k) out[k] = line.slice(i + 1).trim();
  }
  return out;
}

function fillModelSelect(sel, models, value) {
  sel.innerHTML = "";
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m; opt.textContent = m;
    sel.appendChild(opt);
  }
  sel.value = value;
}

async function loadConfig() {
  const cfg = await (await fetch("/api/config")).json();
  allowedModels = cfg.allowed_models || allowedModels;
  fillModelSelect($("#model"), allowedModels, cfg.model || "small");
  fillModelSelect($("#set-model"), allowedModels, cfg.model || "small");
  $("#set-style").value = cfg.default_style || "neutral";
  $("#set-cleanup").value = cfg.cleanup_level || "medium";
  $("#set-language").value = cfg.language || "";
  $("#set-device").value = cfg.device || "auto";
  $("#set-polish").value = cfg.polish_backend || "heuristic";
  $("#set-replacements").value = kvToText(cfg.replacements);
  $("#set-snippets").value = kvToText(cfg.snippets);
}

$("#open-settings").addEventListener("click", async () => {
  openOverlay("#settings-overlay");
  try { await loadConfig(); } catch (err) { status(String(err)); }
});

$("#save-settings").addEventListener("click", async () => {
  try {
    await postJson("/api/config", {
      model: $("#set-model").value,
      default_style: $("#set-style").value,
      cleanup_level: $("#set-cleanup").value,
      language: $("#set-language").value,
      device: $("#set-device").value,
      polish_backend: $("#set-polish").value,
      replacements: textToKv($("#set-replacements").value),
      snippets: textToKv($("#set-snippets").value),
    });
    $("#model").value = $("#set-model").value;
    closeOverlay($("#settings-overlay"));
    status("Réglages enregistrés.");
  } catch (err) { status(String(err)); }
});

/* ---------- Diagnostics ---------- */
const CATEGORY_ORDER = ["Transcription", "Microphone", "Insertion", "System"];

async function loadHealth() {
  const body = $("#health-body");
  body.innerHTML = '<p class="muted">Chargement…</p>';
  let data;
  try { data = await (await fetch("/api/doctor")).json(); }
  catch (err) { body.innerHTML = '<p class="muted">Erreur : ' + err + "</p>"; return; }

  const s = data.summary;
  updateHealthDot(s);
  $("#health-summary").textContent = s.ready ? "Prêt à dicter ✓" : "Configuration incomplète";

  const groups = {};
  for (const c of data.checks) (groups[c.category] = groups[c.category] || []).push(c);

  let html = `<div class="diag-summary">
      <span class="pill ${s.can_transcribe ? "ok" : "bad"}">Transcription ${s.can_transcribe ? "✓" : "✕"}</span>
      <span class="pill ${s.can_record ? "ok" : "bad"}">Micro ${s.can_record ? "✓" : "✕"}</span>
      <span class="pill ${s.can_insert ? "ok" : "bad"}">Insertion ${s.can_insert ? "✓" : "✕"}</span>
    </div>`;

  const cats = CATEGORY_ORDER.filter((c) => groups[c]).concat(Object.keys(groups).filter((c) => !CATEGORY_ORDER.includes(c)));
  for (const cat of cats) {
    html += `<div class="diag-group"><h3>${cat}</h3>`;
    for (const c of groups[cat]) {
      const icon = c.ok ? '<span class="diag-icon ok">✓</span>' : `<span class="diag-icon ${c.essential ? "bad" : "warn"}">!</span>`;
      const req = !c.ok && c.essential ? '<span class="req-badge">requis</span>' : "";
      let fix = "";
      if (!c.ok && c.fix) {
        fix = `<div class="diag-fix"><code>${escapeHtml(c.fix)}</code><button data-copy="${escapeHtml(c.fix)}">Copier</button></div>`;
      }
      html += `<div class="diag-item">${icon}<div class="diag-main">
          <div class="diag-label">${escapeHtml(c.label)}${req}</div>
          ${c.detail ? `<div class="diag-detail">${escapeHtml(c.detail)}</div>` : ""}
          ${fix}
        </div></div>`;
    }
    html += "</div>";
  }
  body.innerHTML = html;
  body.querySelectorAll("[data-copy]").forEach((b) =>
    b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copié ✓"; setTimeout(() => (b.textContent = "Copier"), 1500); }
      catch (_) {}
    })
  );
}

function updateHealthDot(summary) {
  const dot = $("#health-dot");
  dot.classList.remove("ok", "warn", "bad");
  dot.classList.add(summary.ready ? "ok" : (summary.can_transcribe ? "warn" : "bad"));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

$("#open-health").addEventListener("click", () => { openOverlay("#health-overlay"); loadHealth(); });
$("#refresh-health").addEventListener("click", loadHealth);

/* ---------- Init ---------- */
(async function init() {
  try { await loadConfig(); } catch (_) {}
  try {
    const data = await (await fetch("/api/doctor")).json();
    updateHealthDot(data.summary);
    if (!data.summary.ready) heroSub.textContent = "Configuration incomplète — ouvre « Configuration » en haut à droite.";
  } catch (_) {}
})();
