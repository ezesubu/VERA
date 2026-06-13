"use strict";

let pybridge = null;          // Python object via QWebChannel (null in dev.html)
let currentTimeline = null;   // active vera bubble (.tl) of the ACTIVE tab

// tab state
let TABS = [];                // [{id,title,provider,model,mode,compact,events:[]}]
let activeId = null;          // active tab id
let pendingId = null;         // tab awaiting a backend response (commands serialize)
let STATE = null;             // mirror of the active tab (provider/model/mode/compact)

const PERSIST_TYPES = ["user", "progress", "image", "final", "error"];

// ---------- helpers ----------
const $ = (id) => document.getElementById(id);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
function scrollBottom() { const c = $("chat"); c.scrollTop = c.scrollHeight; }
function genId() { return "tab-" + Date.now() + "-" + Math.floor(Math.random() * 1e5); }

function md(text) {
  const raw = marked.parse(text || "");
  const safe = DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["style", "iframe", "form", "object", "embed"],
    FORBID_ATTR: ["onerror", "onload", "onclick", "style"],
  });
  const div = document.createElement("div");
  div.className = "md";
  div.innerHTML = safe;
  div.querySelectorAll("pre code").forEach((el) => hljs.highlightElement(el));
  return div;
}

function userBubble(text) {
  const row = document.createElement("div");
  row.className = "msg row-user";
  const b = document.createElement("div");
  b.className = "user";
  b.textContent = text;
  row.appendChild(b);
  $("chat").appendChild(row);
  return row;
}

function ensureTimeline() {
  if (currentTimeline) return currentTimeline;
  const msg = document.createElement("div");
  msg.className = "msg vera";
  const who = document.createElement("div");
  who.className = "who";
  who.innerHTML = '<span class="av">◇</span><span>VERA</span>';
  const tl = document.createElement("div");
  tl.className = "tl";
  msg.appendChild(who);
  msg.appendChild(tl);
  $("chat").appendChild(msg);
  currentTimeline = tl;
  return tl;
}
function closeTimeline() { stopSpin(); currentTimeline = null; }

// ---------- thinking indicator — the VERA V logo, pulsing (CSS-animated) ----------
const VLOGO = '<svg class="vlogo" viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="45" fill="none" stroke="currentColor" stroke-width="3" opacity="0.5"/><path d="M28 28 L43 28 L50 54 L57 28 L72 28 L50 80 Z" fill="currentColor"/></svg>';
function startSpin() {
  const tl = ensureTimeline();
  if (tl.querySelector(".spin")) return;
  const item = document.createElement("div");
  item.className = "tl-item spin";
  const ic = document.createElement("span");
  ic.innerHTML = VLOGO;
  if (ic.firstChild) item.appendChild(ic.firstChild);
  const label = (STATE && STATE.model) || (STATE && MODELS[STATE.provider] && MODELS[STATE.provider].label) || "VERA";
  item.appendChild(document.createTextNode(label + " · thinking…"));
  tl.appendChild(item);
  scrollBottom();
}
function stopSpin() {
  if (currentTimeline) { const s = currentTimeline.querySelector(".spin"); if (s) s.remove(); }
}

// ============================================================================
// dispatch — single Python→JS entry point
// ============================================================================
window.veraChat = {
  dispatch(e) {
    // ---- global (non-tab) events ----
    switch (e.type) {
      case "restore_tabs": return restoreTabs(e);
      case "status": {
        const st = $("status");
        st.className = e.online ? "" : "off";
        st.title = e.online ? ("live · " + (e.version || "UE")) : "offline";
        return;
      }
      case "models": {
        const prov = String(e.provider || "").toUpperCase();
        if (MODELS[prov]) { MODELS[prov].models = e.models || []; if (e.status) MODELS[prov].status = e.status; }
        if (prov === "LOCAL") renderDetected(e.models || [], e.status);
        applyProviderStatus(prov, e.status);
        autoSelectModel(prov);
        if (pop().classList.contains("open")) renderModels($("pop-q").value);
        return;
      }
      case "conn": {
        const prov = String(e.provider || "").toUpperCase();
        if (MODELS[prov]) MODELS[prov].status = e.ok ? "ok" : "off";
        applyProviderStatus(prov, e.ok ? "ok" : "off", e.detail);
        resetTestButton(prov, e.ok ? "OK" : "✕");
        return;
      }
      case "providers": {
        (e.providers || []).forEach((p) => {
          const id = String(p.id || "").toUpperCase();
          if (!MODELS[id]) MODELS[id] = { label: p.label || id, status: "off", models: [] };
          else if (p.label) MODELS[id].label = p.label;
          MODELS[id].status = p.status || MODELS[id].status;
          MODELS[id].needs_key = p.needs_key;
          applyProviderStatus(id, p.status);
        });
        applyModelLabel();
        if (pop().classList.contains("open")) renderModels($("pop-q").value);
        return;
      }
      case "saved": {
        const prov = String(e.provider || "").toUpperCase();
        if (e.ok) { if (MODELS[prov]) MODELS[prov].status = "ok"; applyProviderStatus(prov, "ok"); }
        else applyProviderStatus(prov, "err", "could not save");
        resetTestButton(prov, e.ok ? "OK" : "✕");
        return;
      }
      case "plugins": return renderPlugins(e.plugins || []);
      case "plugin_set": {
        const row = document.querySelector('.plug[data-id="' + e.id + '"]');
        if (row) { row.classList.toggle("off", !e.enabled); const cb = row.querySelector("input"); if (cb) cb.checked = !!e.enabled; }
        return;
      }
      case "history": { (e.events || []).forEach((ev) => window.veraChat.dispatch(ev)); return; }
    }

    // ---- chat events → route to a tab ----
    const tab = getTab(e._tab) || getTab(pendingId) || activeTab();
    if (!tab) return;

    if (e.type === "user" && (!tab.title || tab.title === "New chat")) {
      tab.title = e.msg.slice(0, 24) + (e.msg.length > 24 ? "…" : "");
      renderTabs();
    }
    if (PERSIST_TYPES.includes(e.type)) tab.events.push(e);

    if (tab === activeTab()) renderEvent(e);

    if (e.type === "final" || e.type === "error" || e.type === "interrupted") {
      pendingId = null;
      persist();
    }
    scrollBottom();
  },
};

// Renders ONE chat event into #chat (the active tab's view).
function renderEvent(e) {
  switch (e.type) {
    case "user": { closeTimeline(); userBubble(e.msg); ensureTimeline(); startSpin(); break; }
    case "progress": {
      stopSpin();
      const tl = ensureTimeline();
      tl.querySelectorAll(".tl-item.working").forEach((el) => { el.classList.remove("working"); el.classList.add("done"); });
      const item = document.createElement("div");
      item.className = "tl-item working";
      const b = document.createElement("b"); b.textContent = e.agent || "";
      item.appendChild(b);
      item.appendChild(document.createTextNode(" — " + (e.msg || "")));
      tl.appendChild(item);
      break;
    }
    case "image": {
      stopSpin();
      const safePath = String(e.path || "");
      const img = document.createElement("img");
      img.className = "shot";
      img.src = "file:///" + safePath.replace(/\\/g, "/");
      img.onclick = () => pybridge && pybridge.open_image(safePath);
      ensureTimeline().appendChild(img);
      break;
    }
    case "final": {
      stopSpin();
      const tl = ensureTimeline();
      tl.querySelectorAll(".tl-item.working").forEach((el) => { el.classList.remove("working"); el.classList.add("done"); });
      const fin = md(e.msg); fin.classList.add("final");
      tl.appendChild(fin);
      if (e.status === "error") tl.classList.add("error");
      closeTimeline();
      break;
    }
    case "thinking": {
      stopSpin();
      const tl = ensureTimeline();
      let th = tl.querySelector(".tl-think.live");
      if (!th) { th = document.createElement("div"); th.className = "tl-item tl-think live"; th.appendChild(document.createTextNode("")); tl.appendChild(th); }
      th.firstChild.textContent += e.msg || "";
      break;
    }
    case "question": {
      stopSpin();
      const tl = ensureTimeline();
      const q = document.createElement("div");
      q.className = "tl-item question";
      const head = document.createElement("div"); head.className = "g-h"; head.textContent = "⚠ destructive action"; q.appendChild(head);
      const txt = document.createElement("div"); txt.textContent = e.msg || "VERA is asking for confirmation."; q.appendChild(txt);
      if (e.args_preview) { const pre = document.createElement("pre"); pre.className = "q-args"; pre.textContent = e.args_preview; q.appendChild(pre); }
      const yes = document.createElement("button"); yes.className = "q-btn approve"; yes.textContent = "✓ Approve";
      const no = document.createElement("button"); no.className = "q-btn deny"; no.textContent = "✕ Reject";
      const acts = document.createElement("div"); acts.className = "q-act"; acts.appendChild(yes); acts.appendChild(no);
      const answer = (v) => {
        if (pybridge) pybridge.answer_question(v);
        acts.remove();
        q.classList.add(v ? "approved" : "denied");
        const verdict = document.createElement("div"); verdict.className = "g-verdict"; verdict.textContent = v ? "✓ approved" : "✕ rejected";
        q.appendChild(verdict);
      };
      yes.onclick = () => answer(true);
      no.onclick = () => answer(false);
      q.appendChild(acts);
      tl.appendChild(q);
      break;
    }
    case "question_resolved": {
      const tl = currentTimeline; if (!tl) break;
      const open = tl.querySelectorAll(".tl-item.question:not(.approved):not(.denied)");
      const q = open[open.length - 1];
      if (q) {
        q.classList.add(e.approved ? "approved" : "denied");
        const acts = q.querySelector(".q-act"); if (acts) acts.remove();
        if (!q.querySelector(".g-verdict")) {
          const verdict = document.createElement("div"); verdict.className = "g-verdict";
          verdict.textContent = e.approved ? "✓ approved" : "✕ rejected (timeout)";
          q.appendChild(verdict);
        }
      }
      break;
    }
    case "error": {
      stopSpin();
      const row = document.createElement("div"); row.className = "msg err";
      const box = document.createElement("div"); box.className = "err-box"; box.appendChild(md(e.msg));
      row.appendChild(box);
      $("chat").appendChild(row);
      break;
    }
    case "interrupted": {
      stopSpin();
      const tl = ensureTimeline();
      tl.querySelectorAll(".tl-item.working").forEach((el) => { el.classList.remove("working"); el.classList.add("interrupted"); });
      const note = document.createElement("div"); note.className = "tl-item interrupted"; note.textContent = "interrupted — the backend stopped responding";
      tl.appendChild(note);
      closeTimeline();
      break;
    }
  }
}

// ============================================================================
// tabs
// ============================================================================
function getTab(id) { return id ? TABS.find((t) => t.id === id) : null; }
function activeTab() { return getTab(activeId); }

function newTab(opts = {}) {
  const t = {
    id: opts.id || genId(),
    title: opts.title || "New chat",
    provider: opts.provider || "LOCAL",
    model: opts.model || "",
    mode: opts.mode || "ask",
    compact: !!opts.compact,
    events: Array.isArray(opts.events) ? opts.events.slice() : [],
  };
  TABS.push(t);
  return t;
}

function switchTab(id) {
  const t = getTab(id); if (!t) return;
  activeId = id;
  STATE = t;
  stopSpin(); currentTimeline = null;
  $("chat").innerHTML = "";
  (t.events || []).forEach((ev) => renderEvent(ev));
  syncDockToTab(t);
  renderTabs();
  scrollBottom();
}

// Styled in-UI confirm modal (no native window.confirm — keeps the aesthetic).
function confirmModal(title, body, onYes) {
  const scrim = document.createElement("div");
  scrim.className = "modal-scrim";
  const card = document.createElement("div");
  card.className = "modal";
  const t = document.createElement("div"); t.className = "m-title"; t.textContent = title;
  const b = document.createElement("div"); b.className = "m-body"; b.textContent = body;
  const acts = document.createElement("div"); acts.className = "m-act";
  const cancel = document.createElement("button"); cancel.className = "m-btn"; cancel.textContent = "Cancel";
  const ok = document.createElement("button"); ok.className = "m-btn danger"; ok.textContent = "Close";
  acts.appendChild(cancel); acts.appendChild(ok);
  card.appendChild(t); card.appendChild(b); card.appendChild(acts);
  scrim.appendChild(card);
  document.body.appendChild(scrim);
  const dismiss = () => scrim.remove();
  cancel.onclick = dismiss;
  scrim.onclick = (e) => { if (e.target === scrim) dismiss(); };
  ok.onclick = () => { dismiss(); onYes(); };
  const onKey = (e) => { if (e.key === "Escape") { dismiss(); document.removeEventListener("keydown", onKey); } };
  document.addEventListener("keydown", onKey);
  setTimeout(() => ok.focus(), 30);
}

function closeTab(id) {
  const t = getTab(id); if (!t) return;
  const doClose = () => {
    const idx = TABS.findIndex((x) => x.id === id);
    TABS.splice(idx, 1);
    if (!TABS.length) newTab({});
    if (activeId === id) { const next = TABS[Math.max(0, idx - 1)] || TABS[0]; activeId = null; switchTab(next.id); }
    else renderTabs();
    persist();
  };
  const hasContent = (t.events || []).some((e) => e.type === "user");
  if (hasContent) confirmModal("Close “" + (t.title || "this chat") + "”?", "This conversation will be lost.", doClose);
  else doClose();
}

function renderTabs() {
  const bar = $("tabbar"); if (!bar) return;
  bar.innerHTML = "";
  TABS.forEach((t) => {
    const el = document.createElement("div");
    el.className = "tab" + (t.id === activeId ? " active" : "");
    el.dataset.id = t.id;
    const name = document.createElement("span"); name.className = "tab-name"; name.textContent = t.title || "New chat";
    el.appendChild(name);
    const x = document.createElement("button"); x.className = "tab-x"; x.textContent = "✕"; x.title = "Close tab";
    x.onclick = (ev) => { ev.stopPropagation(); closeTab(t.id); };
    el.appendChild(x);
    el.onclick = () => switchTab(t.id);
    bar.appendChild(el);
  });
  const add = document.createElement("button");
  add.id = "tab-add"; add.textContent = "+"; add.title = "New chat";
  add.onclick = () => { const t = newTab({}); switchTab(t.id); persist(); };
  bar.appendChild(add);
}

function syncDockToTab(t) {
  applyModelLabel();
  $$("#seg button").forEach((b) => b.classList.toggle("on", b.dataset.m === t.mode));
  const oc = $("opt-compact"); if (oc) oc.checked = !!t.compact;
}

function persist() {
  if (!pybridge) return;
  const data = {
    tabs: TABS.map((t) => ({ id: t.id, title: t.title, provider: t.provider, model: t.model, mode: t.mode, compact: t.compact, events: t.events })),
    active: activeId,
  };
  try { pybridge.save_tabs(JSON.stringify(data)); } catch (e) { /* ignore */ }
}

function restoreTabs(e) {
  if (e.tabs && e.tabs.length) {
    TABS = [];
    e.tabs.forEach((td) => newTab(td));
    activeId = null;
    switchTab((e.active && getTab(e.active)) ? e.active : TABS[0].id);
  }
  // else: keep the default tab created at boot
}

// ============================================================================
// model registry + picker
// ============================================================================
const MODELS = {
  LOCAL:     { label: "LM Studio · Local", status: "off", models: [] },
  ANTHROPIC: { label: "Anthropic", status: "off", models: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"] },
  OPENAI:    { label: "OpenAI", status: "off", models: ["gpt-4o", "gpt-4o-mini", "o3-mini"] },
  GEMINI:    { label: "Gemini", status: "off", models: ["gemini-2.0-flash", "gemini-1.5-pro"] },
};

function applyModelLabel() {
  if (!STATE) return;
  $("mp-name").textContent = STATE.model || "select a model";
  const info = MODELS[STATE.provider] || { status: "off" };
  const live = info.status === "local" || info.status === "online";
  $("mp-dot").className = "mp-dot " + (live ? "local" : (info.status === "ok" ? "on" : "off"));
}

function autoSelectModel(prov) {
  if (!STATE || STATE.model || prov !== STATE.provider) return;
  const list = (MODELS[prov] && MODELS[prov].models) || [];
  if (!list.length) return;
  STATE.model = list[0];
  applyModelLabel();
  if (pybridge) pybridge.set_model(STATE.provider, STATE.model);
  persist();
}

const pop = () => $("pop");

function renderModels(filter = "") {
  const list = $("pop-list");
  list.innerHTML = "";
  const f = (filter || "").toLowerCase();
  let any = false;
  for (const [prov, info] of Object.entries(MODELS)) {
    const matches = (info.models || []).filter((m) => !f || m.toLowerCase().includes(f) || info.label.toLowerCase().includes(f));
    if (!matches.length) continue;
    any = true;
    const grp = document.createElement("div"); grp.className = "grp";
    const live = info.status === "local" || info.status === "online";
    const dotCls = live ? "local" : info.status === "ok" ? "on" : "off";
    const lab = document.createElement("span"); lab.textContent = info.label; grp.appendChild(lab);
    if (prov === "LOCAL") {
      const re = document.createElement("span"); re.className = "rescan"; re.textContent = "↻ rescan";
      re.onclick = (ev) => { ev.stopPropagation(); re.textContent = "scanning…"; requestModels("LOCAL"); setTimeout(() => { re.textContent = "↻ rescan"; }, 1200); };
      grp.appendChild(re);
    } else if (info.status === "off") {
      const nk = document.createElement("span"); nk.style.color = "var(--ink-faint)"; nk.textContent = "no key"; grp.appendChild(nk);
    }
    list.appendChild(grp);
    for (const m of matches) {
      const muted = info.status === "off";
      const sel = STATE && (prov === STATE.provider && m === STATE.model);
      const opt = document.createElement("div");
      opt.className = "opt" + (sel ? " sel" : "") + (muted ? " muted" : "");
      const s = document.createElement("span"); s.className = "s " + dotCls;
      const nm = document.createElement("span"); nm.className = "nm"; nm.textContent = m;
      const pick = document.createElement("span"); pick.className = "pick"; pick.textContent = sel ? "active" : "↵";
      opt.appendChild(s); opt.appendChild(nm); opt.appendChild(pick);
      opt.onclick = () => { if (muted) { openSetup(); return; } selectModel(prov, m); };
      list.appendChild(opt);
    }
  }
  if (!any) {
    const empty = document.createElement("div"); empty.className = "empty";
    empty.textContent = "No models. Configure a provider in ⚙ Setup.";
    list.appendChild(empty);
  }
}

function selectModel(prov, m) {
  if (!STATE) return;
  STATE.provider = prov; STATE.model = m;
  applyModelLabel();
  if (pybridge) pybridge.set_model(prov, m);
  persist();
  closePop();
}
window.__veraDevSelect = (prov, m) => { if (STATE) { STATE.provider = prov; STATE.model = m; applyModelLabel(); } };

function openPop() { renderModels(); pop().classList.add("open"); $("pop-q").value = ""; setTimeout(() => $("pop-q").focus(), 50); }
function closePop() { pop().classList.remove("open"); }

function requestModels(prov) {
  if (pybridge) { pybridge.list_models(prov); return; }
  if (prov === "LOCAL") window.veraChat.dispatch({ type: "models", provider: "LOCAL", status: "online", models: ["qwen2.5-coder-32b-instruct", "llama-3.3-70b-instruct"] });
}

// ---------- setup ----------
function applyProviderStatus(prov, status, detail) {
  const st = $("st-" + prov); if (!st) return;
  switch (status) {
    case "ok": case "configured": st.className = "st ok"; st.textContent = "● configured"; break;
    case "online": case "local": st.className = "st live"; st.textContent = "● online"; break;
    case "offline": st.className = "st no"; st.textContent = "○ offline"; break;
    case "missing_key": case "off": st.className = "st no"; st.textContent = "○ not configured"; break;
    case "err": st.className = "st err"; st.textContent = "✕ " + (detail || "error"); break;
    default: if (status) { st.className = "st no"; st.textContent = "○ " + status; }
  }
}

function renderDetected(models, status) {
  const box = $("lm-list"); box.innerHTML = "";
  (models || []).forEach((m) => {
    const d = document.createElement("div"); d.className = "d";
    const s = document.createElement("span"); s.className = "s";
    d.appendChild(s); d.appendChild(document.createTextNode(m)); box.appendChild(d);
  });
  applyProviderStatus("LOCAL", status || (models && models.length ? "online" : "offline"));
  const lab = $("st-LOCAL");
  if (models && models.length) { lab.className = "st live"; lab.textContent = "● " + models.length + " model" + (models.length > 1 ? "s" : "") + " detected"; }
}

function resetTestButton(prov, label) {
  const b = document.querySelector('.test[data-p="' + prov + '"]');
  if (b) { b.textContent = label || "Test"; setTimeout(() => { b.textContent = "Test"; }, 1400); }
  const ld = $("lm-detect"); if (prov === "LOCAL" && ld) ld.textContent = "Detect";
}

function renderPlugins(list) {
  const box = $("plugins-list"); if (!box) return;
  if (!list || !list.length) {
    box.innerHTML = '<div class="plug-empty">No plugins found. Drop a folder in <code>VERA_Plugins/</code> with <code>tools/</code> and/or a <code>SKILL.md</code>.</div>';
    return;
  }
  box.innerHTML = "";
  list.forEach((p) => {
    const row = document.createElement("div"); row.className = "plug" + (p.enabled ? "" : " off"); row.dataset.id = p.id;
    const body = document.createElement("div"); body.className = "p-body";
    const top = document.createElement("div"); top.className = "p-top";
    const nm = document.createElement("span"); nm.className = "p-name"; nm.textContent = p.name || p.id;
    const ver = document.createElement("span"); ver.className = "p-ver"; ver.textContent = [p.version ? "v" + p.version : "", p.author || ""].filter(Boolean).join(" · ");
    top.appendChild(nm); top.appendChild(ver); body.appendChild(top);
    if (p.description) { const d = document.createElement("div"); d.className = "p-desc"; d.textContent = p.description; body.appendChild(d); }
    const meta = document.createElement("div"); meta.className = "p-meta";
    (p.tools || []).forEach((t) => { const tg = document.createElement("span"); tg.className = "p-tag"; tg.textContent = "⚙ " + t; meta.appendChild(tg); });
    if (p.has_skill) { const sk = document.createElement("span"); sk.className = "p-tag skill"; sk.textContent = "✦ skill"; meta.appendChild(sk); }
    if (!(p.tools && p.tools.length) && !p.has_skill) { const e0 = document.createElement("span"); e0.className = "p-tag"; e0.textContent = "empty"; meta.appendChild(e0); }
    body.appendChild(meta); row.appendChild(body);
    const lab = document.createElement("label"); lab.className = "toggle"; lab.title = "Enable / disable";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!p.enabled;
    const tg = document.createElement("span"); tg.className = "tg";
    cb.onchange = () => { row.classList.toggle("off", !cb.checked); if (pybridge) pybridge.set_plugin(p.id, cb.checked); };
    lab.appendChild(cb); lab.appendChild(tg); row.appendChild(lab);
    box.appendChild(row);
  });
}

function openSetup() { closePop(); $("scrim").classList.add("open"); $("setup").classList.add("open"); }
function closeSetup() { $("scrim").classList.remove("open"); $("setup").classList.remove("open"); }

// ============================================================================
// wiring
// ============================================================================
function wireControls() {
  $("model-pick").onclick = () => pop().classList.contains("open") ? closePop() : openPop();
  $("pop-q").oninput = (e) => renderModels(e.target.value);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closePop(); closeSetup(); } });
  document.addEventListener("click", (e) => { if (!pop().contains(e.target) && !$("model-pick").contains(e.target)) closePop(); });

  $("seg").onclick = (e) => {
    const b = e.target.closest("button"); if (!b || !STATE) return;
    $$("#seg button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    STATE.mode = b.dataset.m;
    if (pybridge) pybridge.set_mode(STATE.mode);
    persist();
  };

  $("gear").onclick = openSetup;
  $("setup-x").onclick = closeSetup;
  $("scrim").onclick = closeSetup;

  $("lm-detect").onclick = function () {
    this.textContent = "…";
    if (pybridge) pybridge.list_models("LOCAL"); else requestModels("LOCAL");
    setTimeout(() => { if (this.textContent === "…") this.textContent = "Detect"; }, 1500);
  };

  $$(".test").forEach((b) => b.onclick = () => {
    const p = b.dataset.p; b.textContent = "…";
    const key = $("k-" + p).value.trim();
    if (pybridge) { if (key) pybridge.save_credentials(p, key); else pybridge.test_connection(p); }
    else setTimeout(() => window.veraChat.dispatch({ type: "conn", provider: p, ok: true, detail: "mock" }), 700);
  });

  const oc = $("opt-compact");
  if (oc) oc.onchange = () => { if (STATE) { STATE.compact = oc.checked; persist(); } if (pybridge) pybridge.set_compact(oc.checked); };
}

function sendCurrent() {
  const text = $("input").value.trim();
  if (!text || !STATE) return;
  $("input").value = ""; $("input").style.height = "auto";
  pendingId = activeId;
  window.veraChat.dispatch({ type: "user", msg: text });
  if (pybridge) {
    pybridge.set_compact(!!STATE.compact);
    pybridge.send_command(text, STATE.provider, STATE.model, STATE.mode, STATE.id);
  }
}

function wireInput() {
  $("send").onclick = sendCurrent;
  $("input").addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendCurrent(); } });
  $("input").addEventListener("input", function () { this.style.height = "auto"; this.style.height = Math.min(this.scrollHeight, 120) + "px"; });
}

// ============================================================================
// boot
// ============================================================================
function boot() {
  wireControls();
  wireInput();
  // always start with one tab; restore_tabs replaces it if there's saved state
  const t = newTab({ title: "New chat" });
  switchTab(t.id);

  if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {
    new QWebChannel(qt.webChannelTransport, (channel) => {
      pybridge = channel.objects.pybridge;
      window.__VERA_HAS_BRIDGE = true;
      pybridge.js_ready();
      pybridge.providers();
      pybridge.list_models("LOCAL");
      pybridge.plugins();
    });
  } else {
    requestModels("LOCAL");
  }
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
