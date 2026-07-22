"use strict";

const $ = (sel) => document.querySelector(sel);
const editor = $("#editor");
const statusEl = $("#status");
const recordBtn = $("#record");
const heroSub = $("#hero-sub");
let recordingSession = null;

/* ---------- i18n ---------- */
const I18N = window.APARTE_I18N || { en: {}, fr: {} };
let lang = localStorage.getItem("aparte_lang");
if (!I18N[lang]) lang = (navigator.language || "en").slice(0, 2);
if (!I18N[lang]) lang = "en";
let recordState = "idle";
let setupIncomplete = false;

function t(key, vars) {
  let s = (I18N[lang] && I18N[lang][key]) || (I18N.en && I18N.en[key]) || key;
  if (vars) for (const k in vars) s = s.replace("{" + k + "}", vars[k]);
  return s;
}
function tKey(key, fallback) {
  const v = (I18N[lang] && I18N[lang][key]) ?? (I18N.en && I18N.en[key]);
  return v !== undefined ? v : fallback;
}

function applyI18n() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
  document.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
  setRecordState(recordState);
  heroSub.textContent = setupIncomplete ? t("hero.sub_incomplete") : t("hero.sub");
  if (lastHealth) updateHealthDot(lastHealth);
  if (!$("#health-overlay").hidden) loadHealth();
}

function status(message, kind) {
  statusEl.textContent = message || "";
  statusEl.classList.toggle("error", kind === "error");
}

async function postJson(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// Contrôles que le traitement rend inopérants : le JS ignorait déjà les clics,
// mais rien ne le montrait à l'écran.
const BUSY_CONTROLS = ["#polish", "#copy", "#paste", "#pick-file"];

function setRecordState(state) {
  recordState = state;
  recordBtn.classList.remove("recording", "processing");
  BUSY_CONTROLS.forEach((sel) => { $(sel).disabled = state === "processing"; });
  const label = recordBtn.querySelector(".record-label");
  if (state === "recording") {
    recordBtn.classList.add("recording");
    label.textContent = t("hero.stop");
  } else if (state === "processing") {
    recordBtn.classList.add("processing");
    label.textContent = t("hero.processing");
  } else {
    label.textContent = t("hero.talk");
  }
}

/* ---------- Transcription ---------- */
async function transcribeBlob(blob) {
  const model = $("#model").value;
  setRecordState("processing");
  status(t("st.transcribing", { model }));
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
      status(data.text.trim() ? t("st.transcript_ready") : t("st.no_speech"));
    }
  } finally {
    setRecordState("idle");
  }
}

async function polishEditor() {
  status(t("st.polishing"));
  const data = await postJson("/api/polish", { text: editor.value });
  editor.value = data.text;
  status(t("st.polished"));
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
      stream.getTracks().forEach((tr) => tr.stop());
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
  if (recordState === "processing") return;
  if (recordingSession) {
    const session = recordingSession;
    recordingSession = null;
    const blob = await session.stop();
    try { await transcribeBlob(blob); } catch (err) { status(String(err), "error"); setRecordState("idle"); }
    return;
  }
  try {
    recordingSession = await startWavRecording();
    setRecordState("recording");
    status(t("st.recording"));
  } catch (err) {
    recordingSession = null;
    status(t("st.mic_error") + err, "error");
  }
});

/* ---------- Action chips ---------- */
$("#polish").addEventListener("click", async () => {
  try { await polishEditor(); } catch (err) { status(String(err), "error"); }
});
$("#pick-file").addEventListener("click", () => $("#file").click());
$("#file").addEventListener("change", async () => {
  const file = $("#file").files[0];
  if (!file) return;
  try { await transcribeBlob(file); } catch (err) { status(String(err), "error"); setRecordState("idle"); }
});
$("#copy").addEventListener("click", async () => {
  status(t("st.copying"));
  try {
    await postJson("/api/copy", { text: editor.value });
    status(t("st.copied"));
  } catch (err) {
    try { await navigator.clipboard.writeText(editor.value); status(t("st.copied_browser")); }
    catch (_) { status(String(err), "error"); }
  }
});
$("#paste").addEventListener("click", async () => {
  status(t("st.pasting"));
  try { await postJson("/api/paste", { text: editor.value }); status(t("st.pasted")); }
  catch (err) { status(String(err), "error"); }
});

/* ---------- Drawers ---------- */
const FOCUSABLE = 'button:not(:disabled), select, textarea, input:not([type="hidden"]), [href], [tabindex]:not([tabindex="-1"])';
let lastFocused = null;

function openOverlay(id) {
  lastFocused = document.activeElement;
  const ov = $(id);
  ov.hidden = false;
  const first = ov.querySelector(FOCUSABLE);
  if (first) first.focus();
}
function closeOverlay(el) {
  el.hidden = true;
  if (lastFocused && document.contains(lastFocused)) lastFocused.focus();
  lastFocused = null;
}
function openOverlayEl() {
  return Array.from(document.querySelectorAll(".overlay")).find((ov) => !ov.hidden) || null;
}

document.querySelectorAll("[data-close]").forEach((b) =>
  b.addEventListener("click", (e) => closeOverlay(e.target.closest(".overlay")))
);
document.querySelectorAll(".overlay").forEach((ov) =>
  ov.addEventListener("click", (e) => { if (e.target === ov) closeOverlay(ov); })
);

// Échap ferme le tiroir, Tab y reste enfermé tant qu'il est ouvert.
document.addEventListener("keydown", (e) => {
  const ov = openOverlayEl();
  if (!ov) return;
  if (e.key === "Escape") { closeOverlay(ov); return; }
  if (e.key !== "Tab") return;
  const items = Array.from(ov.querySelectorAll(FOCUSABLE)).filter((el) => el.offsetParent !== null);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});

/* ---------- Language selector ---------- */
$("#ui-lang").value = lang;
$("#ui-lang").addEventListener("change", () => {
  lang = $("#ui-lang").value;
  localStorage.setItem("aparte_lang", lang);
  applyI18n();
});

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
  $("#set-nbsp").checked = cfg.nonbreaking_spaces !== false;
  $("#set-replacements").value = kvToText(cfg.replacements);
  $("#set-snippets").value = kvToText(cfg.snippets);
}

$("#open-settings").addEventListener("click", async () => {
  openOverlay("#settings-overlay");
  try { await loadConfig(); } catch (err) { status(String(err), "error"); }
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
      nonbreaking_spaces: $("#set-nbsp").checked,
      replacements: textToKv($("#set-replacements").value),
      snippets: textToKv($("#set-snippets").value),
    });
    $("#model").value = $("#set-model").value;
    closeOverlay($("#settings-overlay"));
    status(t("st.settings_saved"));
  } catch (err) { status(String(err), "error"); }
});

/* ---------- Diagnostics ---------- */
const CATEGORY_ORDER = ["Transcription", "Microphone", "Insertion", "System"];

async function loadHealth() {
  const body = $("#health-body");
  body.innerHTML = '<p class="muted">' + t("diag.loading") + "</p>";
  let data;
  try { data = await (await fetch("/api/doctor")).json(); }
  catch (err) { body.innerHTML = '<p class="muted">' + escapeHtml(String(err)) + "</p>"; return; }

  const s = data.summary;
  updateHealthDot(s);
  $("#health-summary").textContent = s.ready ? t("diag.ready") : t("diag.incomplete");

  const groups = {};
  for (const c of data.checks) (groups[c.category] = groups[c.category] || []).push(c);

  let html = `<div class="diag-summary">
      <span class="pill ${s.can_transcribe ? "ok" : "bad"}">${t("diag.pill.transcription")} ${s.can_transcribe ? "✓" : "✕"}</span>
      <span class="pill ${s.can_record ? "ok" : "bad"}">${t("diag.pill.micro")} ${s.can_record ? "✓" : "✕"}</span>
      <span class="pill ${s.can_insert ? "ok" : "bad"}">${t("diag.pill.insertion")} ${s.can_insert ? "✓" : "✕"}</span>
    </div>`;

  const cats = CATEGORY_ORDER.filter((c) => groups[c]).concat(Object.keys(groups).filter((c) => !CATEGORY_ORDER.includes(c)));
  for (const cat of cats) {
    html += `<div class="diag-group"><h3>${escapeHtml(tKey("diag.cat." + cat, cat))}</h3>`;
    for (const c of groups[cat]) {
      const icon = c.ok ? '<span class="diag-icon ok">✓</span>' : `<span class="diag-icon ${c.essential ? "bad" : "warn"}">!</span>`;
      const req = !c.ok && c.essential ? `<span class="req-badge">${t("diag.required")}</span>` : "";
      const label = escapeHtml(tKey("check." + c.key + ".label", c.label));
      const detail = tKey("check." + c.key + ".detail", c.detail);
      let fix = "";
      if (!c.ok && c.fix) {
        fix = `<div class="diag-fix"><code>${escapeHtml(c.fix)}</code><button data-copy="${escapeHtml(c.fix)}">${t("diag.copy")}</button></div>`;
      }
      html += `<div class="diag-item">${icon}<div class="diag-main">
          <div class="diag-label">${label}${req}</div>
          ${detail ? `<div class="diag-detail">${escapeHtml(detail)}</div>` : ""}
          ${fix}
        </div></div>`;
    }
    html += "</div>";
  }

  const h = data.hotkey;
  if (h) {
    const bound = !!h.bound_key;
    const icon = bound ? '<span class="diag-icon ok">✓</span>' : '<span class="diag-icon warn">!</span>';
    const label = bound ? t("hotkey.bound", { key: h.bound_key_label }) : t("hotkey.unbound");
    html += `<div class="diag-group"><h3>${escapeHtml(t("hotkey.title"))}</h3>`;
    html += `<div class="diag-item">${icon}<div class="diag-main">
        <div class="diag-label">${escapeHtml(label)}</div>
        <div class="diag-detail">${escapeHtml(t("hotkey.intro"))}</div>`;
    if (h.supported && !bound) {
      html += `<div class="diag-detail">${escapeHtml(t("hotkey.auto"))}</div>
        <div class="diag-fix"><code>${escapeHtml(h.install_command)}</code><button data-copy="${escapeHtml(h.install_command)}">${t("diag.copy")}</button></div>`;
    }
    html += `<div class="diag-detail">${escapeHtml(t("hotkey.manual", { key: h.default_key_label }))}</div>
        <div class="diag-fix"><code>${escapeHtml(h.command)}</code><button data-copy="${escapeHtml(h.command)}">${t("diag.copy")}</button></div>
      </div></div></div>`;
  }

  body.innerHTML = html;
  body.querySelectorAll("[data-copy]").forEach((b) =>
    b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = t("diag.copied"); setTimeout(() => (b.textContent = t("diag.copy")), 1500); }
      catch (_) {}
    })
  );
}

let lastHealth = null;

// La pastille porte une couleur ; le texte lu par les lecteurs d'écran porte la
// même information sans elle.
function updateHealthDot(summary) {
  lastHealth = summary;
  const state = summary.ready ? "ok" : (summary.can_transcribe ? "warn" : "bad");
  const dot = $("#health-dot");
  dot.classList.remove("ok", "warn", "bad");
  dot.classList.add(state);
  $("#health-dot-text").textContent = t("health." + state);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

$("#open-health").addEventListener("click", () => { openOverlay("#health-overlay"); loadHealth(); });
$("#refresh-health").addEventListener("click", loadHealth);

/* ---------- Init ---------- */
applyI18n();
(async function init() {
  try { await loadConfig(); } catch (_) {}
  try {
    const data = await (await fetch("/api/doctor")).json();
    updateHealthDot(data.summary);
    setupIncomplete = !data.summary.ready;
    heroSub.textContent = setupIncomplete ? t("hero.sub_incomplete") : t("hero.sub");
  } catch (_) {}
})();
