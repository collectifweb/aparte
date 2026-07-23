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
let historyPersist = false;
let livePreview = true;
// Vrai dès qu'un aperçu s'affiche, faux quand la transcription finale a pris sa
// place : tant qu'il est vrai, le texte de l'éditeur est provisoire.
let previewing = false;

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
  renderRecent(recentEntries);
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

// Les trois actions travaillent sur le contenu de l'éditeur : sur un éditeur
// vide elles ne font rien tout en annonçant qu'elles ont réussi, et « Copier »
// va plus loin — il remplace le presse-papiers par du vide. Elles suivent donc
// l'éditeur autant que le traitement. « Importer audio » reste actif : c'est
// lui qui remplit l'éditeur.
const TEXT_ACTIONS = ["#polish", "#copy", "#paste"];

function syncActionState() {
  // Un aperçu compte comme un traitement en cours : polir, copier ou insérer un
  // texte que la passe suivante va réécrire donnerait une version périmée.
  const busy = recordState === "processing" || previewing;
  const empty = !editor.value.trim();
  TEXT_ACTIONS.forEach((sel) => { $(sel).disabled = busy || empty; });
  $("#pick-file").disabled = busy;
}

// Texte tapé ou collé à la main dans l'éditeur : les actions se rallument.
editor.addEventListener("input", syncActionState);

function setRecordState(state) {
  recordState = state;
  recordBtn.classList.remove("recording", "processing");
  syncActionState();
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
    if (editor.value.trim()) recordRecent(editor.value);
  } finally {
    clearPreview();
    setRecordState("idle");
  }
}

async function polishEditor() {
  status(t("st.polishing"));
  const data = await postJson("/api/polish", { text: editor.value });
  editor.value = data.text;
  syncActionState();
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
    // Une photo de ce qui a été capté jusqu'ici, sans rien interrompre :
    // l'enregistrement continue de remplir `chunks` derrière.
    snapshot() {
      return encodeWav(chunks, sampleRate);
    },
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

/* ---------- Aperçu au fil de la parole ---------- */
// Chaque passe re-transcrit tout l'audio depuis le début. Whisper n'a pas d'état
// à reprendre là où il s'était arrêté, et c'est ce qui lui permet de corriger ses
// propres erreurs une fois qu'il a entendu la suite de la phrase.
//
// Une seule passe en vol à la fois, et la suivante n'est programmée qu'au retour
// de la précédente : sur une machine lente il y a simplement moins d'aperçus,
// jamais une file qui s'allonge. Le serveur applique la même règle de son côté.
const PREVIEW_GAP_MS = 1200;
let previewTimer = null;

function startPreviewLoop(session) {
  if (!livePreview) return;
  const tick = async () => {
    previewTimer = null;
    // L'enregistrement s'est arrêté pendant qu'on attendait : plus rien à faire.
    if (recordingSession !== session) return;
    try {
      const res = await fetch("/api/transcribe?preview=1&model=" + encodeURIComponent($("#model").value), {
        method: "POST",
        headers: { "Content-Type": "audio/wav" },
        body: session.snapshot(),
      });
      if (res.ok && recordingSession === session) {
        const data = await res.json();
        // `text` est nul quand le serveur transcrivait déjà : la passe a
        // simplement laissé son tour.
        if (typeof data.text === "string") showPreview(data.text);
      }
    } catch (_) {
      // Un aperçu raté ne dit rien sur la dictée en cours, qui continue. Se
      // plaindre ici couvrirait l'écran de messages pour rien.
    }
    if (recordingSession === session) previewTimer = setTimeout(tick, PREVIEW_GAP_MS);
  };
  previewTimer = setTimeout(tick, PREVIEW_GAP_MS);
}

function stopPreviewLoop() {
  clearTimeout(previewTimer);
  previewTimer = null;
}

function showPreview(text) {
  // Un silence en début de dictée ne doit pas vider l'éditeur.
  if (!text.trim()) return;
  if (!previewing) status(t("st.preview"));
  previewing = true;
  editor.classList.add("previewing");
  editor.value = text;
  syncActionState();
}

function clearPreview() {
  previewing = false;
  editor.classList.remove("previewing");
}

/* ---------- Record button ---------- */
recordBtn.addEventListener("click", async () => {
  if (recordState === "processing") return;
  if (recordingSession) {
    const session = recordingSession;
    recordingSession = null;
    stopPreviewLoop();
    const blob = await session.stop();
    try { await transcribeBlob(blob); } catch (err) { status(String(err), "error"); clearPreview(); setRecordState("idle"); }
    return;
  }
  try {
    recordingSession = await startWavRecording();
    setRecordState("recording");
    status(t("st.recording"));
    startPreviewLoop(recordingSession);
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
function listToText(list) { return (list || []).join("\n"); }
function textToList(text) {
  return (text || "").split("\n").map((line) => line.trim()).filter(Boolean);
}

// Une ligne sans « = » était jetée en silence : on fermait le tiroir en croyant
// avoir appris un mot à Aparté, et rien n'avait changé. Elle est maintenant
// refusée en pointant son numéro. Exception, dans les raccourcis dictés
// seulement : la suite d'un texte de plusieurs lignes n'a évidemment pas de
// « = ». Ce cas-là se perdait lui aussi — la signature donnée en exemple sous
// le champ ne survivait pas à un enregistrement.
function parseKv(text, multiline) {
  const entries = {};
  const bad = [];
  let last = null;
  (text || "").split("\n").forEach((line, index) => {
    if (!line.trim()) return;
    const i = line.indexOf("=");
    if (i === -1) {
      if (multiline && last) entries[last] += "\n" + line.trim();
      else bad.push(index + 1);
      return;
    }
    const key = line.slice(0, i).trim();
    if (!key) { bad.push(index + 1); return; }
    entries[key] = line.slice(i + 1).trim();
    last = key;
  });
  return { entries, bad };
}

// Le message reste dans le tiroir. Écrit dans la ligne d'état de la page, il
// tombait derrière le voile du tiroir ouvert.
function settingsError(message) {
  const box = $("#settings-error");
  box.textContent = message || "";
  box.hidden = !message;
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
  livePreview = cfg.live_preview !== false;
  $("#set-live-preview").checked = livePreview;
  $("#set-polish").value = cfg.polish_backend || "heuristic";
  $("#set-nbsp").checked = cfg.nonbreaking_spaces !== false;
  $("#set-numbers").value = String(cfg.numbers_from ?? 10);
  $("#set-short-text").value = String(cfg.short_text_words || 0);
  $("#set-trailing-space").checked = cfg.trailing_space === true;
  $("#set-beep").checked = cfg.beep === true;
  $("#set-paste-mode").value = cfg.paste_mode || "clipboard";
  historyPersist = cfg.history_persist === true;
  $("#set-history-persist").checked = historyPersist;
  $("#set-hotwords").value = listToText(cfg.hotwords);
  $("#set-replacements").value = kvToText(cfg.replacements);
  $("#set-snippets").value = kvToText(cfg.snippets);
  await loadMicrophones(cfg.microphone || "");
}

// Le micro branché après l'ouverture du panneau n'apparaîtrait pas : d'où le
// bouton Actualiser, qui refait l'inventaire sans perdre le choix en cours.
async function loadMicrophones(selected) {
  const sel = $("#set-microphone");
  const keep = selected !== undefined ? selected : sel.value;
  let devices = [];
  try { devices = (await (await fetch("/api/microphones")).json()).devices || []; }
  catch (err) { devices = []; }
  sel.innerHTML = "";
  const auto = document.createElement("option");
  auto.value = ""; auto.textContent = t("set.microphone_default");
  auto.dataset.i18n = "set.microphone_default";
  sel.appendChild(auto);
  for (const device of devices) {
    const opt = document.createElement("option");
    opt.value = device.name; opt.textContent = device.label;
    sel.appendChild(opt);
  }
  // Un micro débranché depuis le dernier enregistrement : on le garde dans la
  // liste, sinon l'enregistrement suivant le remplacerait en silence.
  if (keep && !devices.some((device) => device.name === keep)) {
    const missing = document.createElement("option");
    missing.value = keep; missing.textContent = t("set.microphone_missing", { name: keep });
    sel.appendChild(missing);
  }
  sel.value = keep;
  // Aucune entrée : la liste se réduirait en silence à « micro par défaut »,
  // alors que le raccourci global, lui, n'a plus de quoi enregistrer.
  $("#microphone-empty").hidden = devices.length > 0;
}

$("#refresh-microphones").addEventListener("click", () => loadMicrophones());

$("#open-settings").addEventListener("click", async () => {
  openOverlay("#settings-overlay");
  settingsError("");
  try { await loadConfig(); } catch (err) { settingsError(String(err)); }
});

$("#save-settings").addEventListener("click", async () => {
  const vocabulary = [
    { selector: "#set-replacements", label: "set.replacements", parsed: parseKv($("#set-replacements").value, false) },
    { selector: "#set-snippets", label: "set.snippets", parsed: parseKv($("#set-snippets").value, true) },
  ];
  const wrong = vocabulary.find((field) => field.parsed.bad.length);
  if (wrong) {
    settingsError(t("set.kv_error", { field: t(wrong.label), line: wrong.parsed.bad[0] }));
    $(wrong.selector).focus();
    return;
  }
  settingsError("");
  try {
    await postJson("/api/config", {
      model: $("#set-model").value,
      default_style: $("#set-style").value,
      cleanup_level: $("#set-cleanup").value,
      language: $("#set-language").value,
      device: $("#set-device").value,
      live_preview: $("#set-live-preview").checked,
      polish_backend: $("#set-polish").value,
      nonbreaking_spaces: $("#set-nbsp").checked,
      numbers_from: Number($("#set-numbers").value),
      short_text_words: Number($("#set-short-text").value),
      trailing_space: $("#set-trailing-space").checked,
      microphone: $("#set-microphone").value,
      beep: $("#set-beep").checked,
      paste_mode: $("#set-paste-mode").value,
      history_persist: $("#set-history-persist").checked,
      hotwords: textToList($("#set-hotwords").value),
      replacements: vocabulary[0].parsed.entries,
      snippets: vocabulary[1].parsed.entries,
    });
    $("#model").value = $("#set-model").value;
    closeOverlay($("#settings-overlay"));
    status(t("st.settings_saved"));
  } catch (err) { settingsError(String(err)); }
});

/* ---------- Diagnostics ---------- */
const CATEGORY_ORDER = ["Transcription", "Microphone", "Insertion", "System"];

async function loadHealth() {
  // Un redessin en pleine mise à jour effacerait le journal en cours.
  if (updateBusy) return;
  const body = $("#health-body");
  body.innerHTML = '<p class="muted">' + t("diag.loading") + "</p>";
  let data;
  try { data = await (await fetch("/api/doctor")).json(); }
  catch (err) {
    // Le tiroir garde son bouton « Rafraîchir » : la phrase y renvoie plutôt
    // que de laisser l'utilisateur devant une erreur JavaScript brute.
    body.innerHTML = '<p class="muted">' + escapeHtml(t("diag.error")) + "</p>"
      + '<p class="diag-detail">' + escapeHtml(String(err)) + "</p>";
    return;
  }

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

  html += `<div class="diag-group"><h3>${escapeHtml(t("update.title"))}</h3>
      <div id="update-body"><p class="diag-detail">${escapeHtml(t("diag.loading"))}</p></div>
    </div>`;

  body.innerHTML = html;
  loadUpdate(false);
  wireCopyButtons(body);
}

function wireCopyButtons(root) {
  root.querySelectorAll("[data-copy]").forEach((b) =>
    b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = t("diag.copied"); setTimeout(() => (b.textContent = t("diag.copy")), 1500); }
      catch (_) {}
    })
  );
}

/* ---------- Dictées récentes ---------- */
// L'historique vit en mémoire vive : il est vide à chaque ouverture de session,
// et cet état vide est donc la situation normale. Il enseigne le raccourci
// global plutôt que d'annoncer son propre vide.
let hotkeyInfo = null;
let recentEntries = [];

async function loadRecent() {
  try {
    renderRecent((await (await fetch("/api/history")).json()).entries || []);
  } catch (_) {}
}

async function recordRecent(text) {
  try {
    renderRecent((await postJson("/api/history", { text })).entries || []);
  } catch (_) {}
}

function renderRecent(entries) {
  recentEntries = entries;
  const box = $("#recent");
  if (!entries.length) {
    box.innerHTML = emptyRecent();
    wireCopyButtons(box);
    return;
  }
  box.innerHTML = entries
    .map(
      (entry, index) => `<button class="recent-item" data-index="${index}" title="${escapeHtml(t("recent.copy"))}">
        <span class="recent-text">${escapeHtml(entry.text)}</span>
        <span class="recent-when">${escapeHtml(relativeTime(entry.at))}</span>
      </button>`
    )
    .join("");
  box.querySelectorAll(".recent-item").forEach((button) =>
    button.addEventListener("click", () => copyRecent(entries[+button.dataset.index].text))
  );
}

function emptyRecent() {
  const key = hotkeyInfo && hotkeyInfo.bound_key_label;
  const fix =
    !key && hotkeyInfo && hotkeyInfo.supported
      ? `<div class="diag-fix"><code>${escapeHtml(hotkeyInfo.install_command)}</code><button data-copy="${escapeHtml(hotkeyInfo.install_command)}">${t("diag.copy")}</button></div>`
      : "";
  return `<div class="recent-empty">
      <span>${escapeHtml(key ? t("recent.hotkey_bound", { key }) : t("recent.hotkey_unbound"))}</span>
      ${fix}
      <span>${escapeHtml(t(historyPersist ? "recent.local_kept" : "recent.local"))}</span>
    </div>`;
}

async function copyRecent(text) {
  status(t("st.copying"));
  try {
    await postJson("/api/copy", { text });
    status(t("st.copied"));
  } catch (err) {
    try { await navigator.clipboard.writeText(text); status(t("st.copied_browser")); }
    catch (_) { status(String(err), "error"); }
  }
}

function relativeTime(at) {
  const seconds = Math.max(0, Date.now() / 1000 - (at || 0));
  if (seconds < 60) return t("time.now");
  if (seconds < 3600) return t("time.minutes", { n: Math.round(seconds / 60) });
  return t("time.hours", { n: Math.round(seconds / 3600) });
}

/* ---------- Mise à jour ---------- */
// Ligne que le serveur écrit seule quand la mise à jour a réussi : elle distingue
// « le journal s'est arrêté » de « c'est installé ».
const UPDATE_DONE = "__APARTE_UPDATED__";
let updateBusy = false;

// Aucune vérification automatique : à l'ouverture du panneau on se contente de ce
// que git sait déjà en local. Le réseau n'est joint que sur clic.
async function loadUpdate(fromRemote) {
  const box = $("#update-body");
  if (!box) return;
  box.innerHTML = `<p class="diag-detail">${escapeHtml(t(fromRemote ? "update.checking" : "diag.loading"))}</p>`;
  try {
    renderUpdate(await (await fetch("/api/update/check" + (fromRemote ? "?fetch=1" : ""))).json());
  } catch (err) {
    box.innerHTML = `<p class="diag-detail">${escapeHtml(String(err))}</p>`;
  }
}

function renderUpdate(data) {
  const box = $("#update-body");
  if (!box) return;
  const fresh = data.state === "current";
  // Une version, pas un nombre de commits : ce qui n'a pas été publié n'est pas
  // une mise à jour.
  const label = data.state !== "available"
    ? t("update." + data.state, { branch: data.branch || "" })
    : t("update.available", { release: (data.release || "").replace(/^v/, "") });

  let html = `<div class="diag-item">
      <span class="diag-icon ${fresh ? "ok" : "warn"}">${fresh ? "✓" : "!"}</span>
      <div class="diag-main"><div class="diag-label">${escapeHtml(label)}</div>`;
  if (data.version) html += `<div class="diag-detail">${escapeHtml(t("update.version", { version: data.version }))}</div>`;
  if (data.detail) html += `<div class="diag-detail">${escapeHtml(data.detail)}</div>`;
  if (data.commits && data.commits.length) {
    html += `<ul class="update-commits">${data.commits.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>`;
  }
  if (data.dirty) html += `<div class="diag-detail">${escapeHtml(t("update.dirty"))}</div>`;
  html += `<div class="update-actions">
        <button class="btn ghost" id="update-check">${escapeHtml(t("update.check"))}</button>
        ${data.state === "available" && !data.dirty ? `<button class="btn primary" id="update-apply">${escapeHtml(t("update.apply"))}</button>` : ""}
      </div>
      <div class="diag-detail" id="update-note">${escapeHtml(t("update.local"))}</div>
      <pre class="update-log" id="update-log" hidden></pre>
    </div></div>`;

  box.innerHTML = html;
  $("#update-check").addEventListener("click", () => loadUpdate(true));
  const apply = $("#update-apply");
  if (apply) apply.addEventListener("click", runUpdate);
}

async function runUpdate() {
  if (updateBusy) return;
  updateBusy = true;
  const log = $("#update-log");
  const note = $("#update-note");
  const buttons = [$("#update-check"), $("#update-apply")].filter(Boolean);
  buttons.forEach((b) => (b.disabled = true));
  note.textContent = t("update.applying");
  log.hidden = false;
  log.textContent = "";

  let text = "";
  try {
    const reader = (await fetch("/api/update/apply", { method: "POST" })).body.getReader();
    const decoder = new TextDecoder();
    for (;;) {
      const chunk = await reader.read();
      if (chunk.value) text += decoder.decode(chunk.value, { stream: true });
      log.textContent = text.split("\n").filter((line) => line !== UPDATE_DONE).join("\n");
      log.scrollTop = log.scrollHeight;
      if (chunk.done) break;
    }
  } catch (err) {
    text += "\n" + String(err);
    log.textContent = text;
  }

  const installed = text.split("\n").includes(UPDATE_DONE);
  note.textContent = t(installed ? "update.restarting" : "update.failed");
  if (installed) return waitForRestart(note);
  updateBusy = false;
  buttons.forEach((b) => (b.disabled = false));
}

async function waitForRestart(note) {
  // Le serveur ne se remplace qu'une seconde après avoir fini de répondre :
  // interroger tout de suite tomberait sur l'ancien processus, et la page se
  // rechargerait juste avant qu'il ne meure.
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  await wait(3000);
  for (let i = 0; i < 40; i++) {
    try {
      if ((await fetch("/api/config", { cache: "no-store" })).ok) return location.reload();
    } catch (_) {}
    await wait(800);
  }
  note.textContent = t("update.no_restart");
  updateBusy = false;
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
    hotkeyInfo = data.hotkey || null;
    setupIncomplete = !data.summary.ready;
    heroSub.textContent = setupIncomplete ? t("hero.sub_incomplete") : t("hero.sub");
  } catch (_) {}
  // Après le diagnostic : l'état vide affiche le raccourci qu'il vient d'y lire.
  loadRecent();
  // Entrée « Réglages » du menu de la barre système : elle ouvre cette page
  // avec le tiroir déjà déplié.
  if (location.hash === "#settings") openOverlay("#settings-overlay");
})();
