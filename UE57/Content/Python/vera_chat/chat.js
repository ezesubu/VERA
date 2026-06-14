"use strict";

let pybridge = null;          // Python object via QWebChannel (null in dev.html)
let currentTimeline = null;   // active vera bubble (.tl) of the ACTIVE tab

// tab state
let TABS = [];                // [{id,title,provider,model,mode,compact,events:[]}]
let activeId = null;          // active tab id
let pendingId = null;         // tab awaiting a backend response (commands serialize)
let STATE = null;             // mirror of the active tab (provider/model/mode/compact)
let __online = false;         // backend/editor reachable
let __version = "";           // editor version (for the logo tooltip)
let pendingImage = null;      // {data, media_type} attached to the next command
let COMMANDS = [];            // tool catalog for the / slash menu
let slashState = null;        // {level, items, idx, cmd} when the / menu is open
let lastDay = null;           // day key of the last rendered turn (for date separators)
let windowFromTurn = 0;       // first turn index currently in the DOM (windowed scroll)
const WINDOW_TURNS = 25;      // turns shown initially / kept in the DOM window
const EARLIER_CHUNK = 20;     // turns loaded each time you scroll up / click "earlier"
const PERSIST_CAP_TURNS = 60; // cap persisted turns per tab (disk optimization)

const PERSIST_TYPES = ["user", "say", "tool_use", "progress", "image", "final", "error"];

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
  // copy button on each code block
  div.querySelectorAll("pre").forEach((pre) => {
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.textContent = "copy";
    btn.onclick = () => {
      const code = pre.querySelector("code");
      const txt = code ? code.textContent : pre.textContent;
      copyText(txt);
      btn.textContent = "copied"; setTimeout(() => { btn.textContent = "copy"; }, 1200);
    };
    pre.appendChild(btn);
  });
  return div;
}

function copyText(txt) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(txt).catch(() => fallbackCopy(txt));
  } else { fallbackCopy(txt); }
}
function fallbackCopy(txt) {
  const ta = document.createElement("textarea");
  ta.value = txt; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } catch (e) { /* ignore */ }
  ta.remove();
}

function userBubble(text, image) {
  const row = document.createElement("div");
  row.className = "msg row-user";
  const b = document.createElement("div");
  b.className = "user";
  if (image && image.data) {
    const img = document.createElement("img");
    img.className = "user-img";
    img.src = "data:" + (image.media_type || "image/png") + ";base64," + image.data;
    b.appendChild(img);
  }
  if (text) {
    const t = document.createElement("div");
    t.textContent = text;
    b.appendChild(t);
  }
  row.appendChild(b);
  $("chat").appendChild(row);
  return row;
}

// ---------- date separators ("Today" / "Yesterday" / "Jun 13") ----------
function dayKey(ts) { const d = new Date(ts || Date.now()); return d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate(); }
function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
function dayLabel(ts) {
  const d = new Date(ts || Date.now());
  const today = new Date(); const yest = new Date(); yest.setDate(today.getDate() - 1);
  if (sameDay(d, today)) return "Today";
  if (sameDay(d, yest)) return "Yesterday";
  const opts = { month: "short", day: "numeric" };
  if (d.getFullYear() !== today.getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString(undefined, opts);
}
function maybeDateSep(ts) {
  const k = dayKey(ts);
  if (k === lastDay) return;
  lastDay = k;
  const sep = document.createElement("div");
  sep.className = "day-sep";
  const s = document.createElement("span"); s.textContent = dayLabel(ts);
  sep.appendChild(s);
  $("chat").appendChild(sep);
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
        __online = !!e.online;
        __version = e.version || "UE";
        refreshBrand();
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
        if (row) {
          row.classList.toggle("off", !e.enabled);
          const cb = row.querySelector("input"); if (cb) cb.checked = !!e.enabled;
          if (e.msg) {
            let note = row.querySelector(".plug-note");
            if (!note) { note = document.createElement("div"); note.className = "plug-note"; row.appendChild(note); }
            note.textContent = e.msg;
          }
        }
        return;
      }
      case "local_config": {
        if ($("lm-url") && e.url) $("lm-url").value = e.url;
        if ($("lm-timeout") && e.timeout_s) $("lm-timeout").value = Math.round(e.timeout_s / 60);
        return;
      }
      case "commands": { COMMANDS = e.commands || []; if (slashState) renderSlash(); return; }
      case "history": { (e.events || []).forEach((ev) => window.veraChat.dispatch(ev)); return; }
    }

    // ---- chat events → route to a tab ----
    const tab = getTab(e._tab) || getTab(pendingId) || activeTab();
    if (!tab) return;

    if (e.type === "user" && (!tab.title || tab.title === "New chat")) {
      tab.title = e.msg.slice(0, 24) + (e.msg.length > 24 ? "…" : "");
      renderTabs();
    }
    if (!e._ts) e._ts = Date.now();
    if (PERSIST_TYPES.includes(e.type)) tab.events.push(e);

    if (tab === activeTab()) {
      const es = $("chat").querySelector(".empty-state");
      if (es) es.remove();
      renderEvent(e);
    }

    if (e.type === "final" || e.type === "error" || e.type === "interrupted") {
      pendingId = null;
      persist();
      updateSendButton();
    }
    scrollBottom();
  },
};

// Renders ONE chat event into #chat (the active tab's view).
function renderEvent(e) {
  switch (e.type) {
    case "user": {
      closeTimeline();
      maybeDateSep(e._ts);
      const r = userBubble(e.msg, e.image);
      if (e._ts) r.title = new Date(e._ts).toLocaleString();
      ensureTimeline(); startSpin();
      break;
    }
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
    case "say": {  // the model's narration ("I'll do X…") alongside its tool calls
      stopSpin();
      const tl = ensureTimeline();
      const item = document.createElement("div");
      item.className = "tl-item say";
      item.appendChild(md(e.msg));
      tl.appendChild(item);
      break;
    }
    case "tool_use": {  // VERA is calling a tool — show its name + args
      stopSpin();
      const tl = ensureTimeline();
      const item = document.createElement("div");
      item.className = "tl-item tool";
      const nm = document.createElement("span"); nm.className = "t-name"; nm.textContent = e.agent || "tool";
      item.appendChild(nm);
      let a = "";
      try { a = typeof e.input === "string" ? e.input : JSON.stringify(e.input); } catch (_) { a = String(e.input); }
      if (a && a !== "{}" && a !== "null" && a !== '""') {
        const arg = document.createElement("span"); arg.className = "t-arg";
        arg.textContent = " " + (a.length > 90 ? a.slice(0, 90) + "…" : a);
        item.appendChild(arg);
      }
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

// Group a flat event list into turns (each `user` message starts a turn).
function splitTurns(events) {
  const turns = [];
  let cur = null;
  (events || []).forEach((e) => {
    if (e.type === "user") { cur = [e]; turns.push(cur); }
    else if (cur) { cur.push(e); }
    else { cur = [e]; turns.push(cur); }  // leading non-user events (greeting)
  });
  return turns;
}

// Render only the windowed slice of turns into #chat. keepScroll preserves the
// viewport when prepending older turns.
function renderWindow(t, keepScroll) {
  const chat = $("chat");
  const prevH = chat.scrollHeight, prevTop = chat.scrollTop;
  stopSpin(); currentTimeline = null; lastDay = null;
  chat.innerHTML = "";
  const turns = splitTurns(t.events);
  if (!turns.length) { renderEmptyState(); return; }
  if (windowFromTurn > turns.length) windowFromTurn = Math.max(0, turns.length - WINDOW_TURNS);
  if (windowFromTurn > 0) {
    const pill = document.createElement("button");
    pill.className = "earlier";
    pill.textContent = "↑ Show earlier (" + windowFromTurn + ")";
    pill.onclick = loadEarlier;
    chat.appendChild(pill);
  }
  for (let i = windowFromTurn; i < turns.length; i++) {
    turns[i].forEach((ev) => renderEvent(ev));
  }
  if (keepScroll) chat.scrollTop = Math.max(0, chat.scrollHeight - prevH + prevTop);
  else scrollBottom();
}

function loadEarlier() {
  const t = activeTab(); if (!t || windowFromTurn === 0) return;
  windowFromTurn = Math.max(0, windowFromTurn - EARLIER_CHUNK);
  renderWindow(t, true);  // keep the viewport on the same content
}

function switchTab(id) {
  const t = getTab(id); if (!t) return;
  activeId = id;
  STATE = t;
  windowFromTurn = Math.max(0, splitTurns(t.events).length - WINDOW_TURNS);
  renderWindow(t, false);
  syncDockToTab(t);
  renderTabs();
  updateSendButton();
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
  syncCompactToggle();
}

// Compact prompt is automatic for LOCAL providers — show it checked + locked.
function syncCompactToggle() {
  const oc = $("opt-compact"); if (!oc || !STATE) return;
  const isLocal = STATE.provider === "LOCAL";
  oc.checked = isLocal ? true : !!STATE.compact;
  oc.disabled = isLocal;
  const lbl = oc.closest(".toggle");
  if (lbl) lbl.classList.toggle("auto", isLocal);
}

// Keep only the last PERSIST_CAP_TURNS turns on disk (unbounded chats are wasteful).
function capEvents(events) {
  const turns = splitTurns(events);
  if (turns.length <= PERSIST_CAP_TURNS) return events;
  return turns.slice(turns.length - PERSIST_CAP_TURNS).reduce((a, t) => a.concat(t), []);
}

function persist() {
  if (!pybridge) return;
  const data = {
    tabs: TABS.map((t) => ({ id: t.id, title: t.title, provider: t.provider, model: t.model, mode: t.mode, compact: t.compact, events: capEvents(t.events) })),
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
  refreshBrand();
}

// The header logo is full amber only when VERA is connected AND a model is ready
// to start; gray otherwise (offline, or connected but no model picked yet).
function refreshBrand() {
  const st = $("status"); if (!st) return;
  const info = (STATE && MODELS[STATE.provider]) || { status: "off" };
  const modelReady = !!(STATE && STATE.model) && ["ok", "online", "local"].includes(info.status);
  const ready = __online && modelReady;
  st.className = ready ? "" : "off";
  st.title = ready ? ("ready · " + (__version || "UE"))
                   : (__online ? "connected — pick a model" : "offline");
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
  syncCompactToggle();
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

// ============================================================================
// / slash command menu + empty-state suggestions
// ============================================================================
const SUGGESTIONS = [
  "List all actors in the current level",
  "Make the scene cyberpunk",
  "What's missing in this project?",
  "Find assets named boss",
];

function slashOpen() { return $("slash").classList.contains("open"); }
function closeSlash() { $("slash").classList.remove("open"); slashState = null; }

function refreshSlash() {
  const v = $("input").value;
  if (v.startsWith("/")) {
    if (slashState && slashState.level === 2) slashState = null;
    renderSlash();
  } else if (slashState && slashState.level === 2 && v.startsWith(slashState.cmd.name + " ")) {
    renderSlash();
  } else {
    closeSlash();
  }
}

function renderSlash() {
  const el = $("slash");
  el.innerHTML = "";
  // level 2: enum values for a chosen command
  if (slashState && slashState.level === 2) {
    const cmd = slashState.cmd;
    const enumArg = cmd.args.find((a) => a.enum && a.enum.length);
    const tail = $("input").value.slice(cmd.name.length + 1).trim().toLowerCase();
    const vals = (enumArg ? enumArg.enum : []).filter((x) => !tail || x.toLowerCase().includes(tail));
    slashState.items = vals;
    if (slashState.idx >= vals.length) slashState.idx = 0;
    const head = document.createElement("div"); head.className = "slash-head";
    head.textContent = cmd.name + " · " + (enumArg ? enumArg.name : "value");
    el.appendChild(head);
    vals.forEach((v, i) => {
      const it = document.createElement("div");
      it.className = "slash-item" + (i === slashState.idx ? " on" : "");
      const nm = document.createElement("span"); nm.className = "s-cmd"; nm.textContent = v;
      it.appendChild(nm);
      it.onmousedown = (ev) => { ev.preventDefault(); pickEnum(v); };
      el.appendChild(it);
    });
    if (!vals.length) { const e0 = document.createElement("div"); e0.className = "slash-empty"; e0.textContent = "type a value…"; el.appendChild(e0); }
    el.classList.add("open");
    return;
  }
  // level 1: commands filtered by the text after "/"
  const f = $("input").value.slice(1).toLowerCase();
  const items = COMMANDS.filter((c) =>
    !f || c.name.toLowerCase().includes(f) || (c.desc || "").toLowerCase().includes(f) || (c.plugin || "").toLowerCase().includes(f)
  ).slice(0, 40);
  const prevIdx = slashState ? slashState.idx : 0;
  slashState = { level: 1, items, idx: Math.min(prevIdx, Math.max(0, items.length - 1)), cmd: null };
  if (!items.length) {
    const e0 = document.createElement("div"); e0.className = "slash-empty"; e0.textContent = "no command matches";
    el.appendChild(e0); el.classList.add("open"); return;
  }
  items.forEach((c, i) => {
    const it = document.createElement("div");
    it.className = "slash-item" + (i === slashState.idx ? " on" : "");
    const nm = document.createElement("span"); nm.className = "s-cmd"; nm.textContent = c.name;
    if (c.plugin) { const b = document.createElement("span"); b.className = "s-plug"; b.textContent = c.plugin; nm.appendChild(b); }
    const ds = document.createElement("span"); ds.className = "s-desc"; ds.textContent = c.desc || "";
    it.appendChild(nm); it.appendChild(ds);
    it.onmousedown = (ev) => { ev.preventDefault(); pickCommand(c); };
    el.appendChild(it);
  });
  el.classList.add("open");
}

function pickCommand(c) {
  const enumArg = c.args && c.args.find((a) => a.enum && a.enum.length);
  $("input").value = c.name + " ";
  if (enumArg) { slashState = { level: 2, cmd: c, items: enumArg.enum, idx: 0 }; renderSlash(); }
  else closeSlash();
  $("input").focus();
}
function pickEnum(v) {
  $("input").value = slashState.cmd.name + " " + v;
  closeSlash();
  $("input").focus();
}
function slashSelect() {
  if (!slashState) return false;
  const item = slashState.items[slashState.idx];
  if (item === undefined) return false;
  if (slashState.level === 2) pickEnum(item); else pickCommand(item);
  return true;
}
function slashMove(d) {
  if (!slashState || !slashState.items.length) return;
  slashState.idx = (slashState.idx + d + slashState.items.length) % slashState.items.length;
  renderSlash();
}

function renderEmptyState() {
  const chat = $("chat");
  const wrap = document.createElement("div"); wrap.className = "empty-state";
  const ic = document.createElement("span"); ic.innerHTML = VLOGO;
  if (ic.firstChild) { ic.firstChild.classList.add("es-logo"); wrap.appendChild(ic.firstChild); }
  const h = document.createElement("div"); h.className = "es-title"; h.textContent = "What are we building?"; wrap.appendChild(h);
  const hint = document.createElement("div"); hint.className = "es-hint"; hint.textContent = "Type / for commands, or try:"; wrap.appendChild(hint);
  const chips = document.createElement("div"); chips.className = "es-chips";
  SUGGESTIONS.forEach((s) => {
    const c = document.createElement("button"); c.className = "es-chip"; c.textContent = s;
    c.onclick = () => { $("input").value = s; $("input").focus(); };
    chips.appendChild(c);
  });
  wrap.appendChild(chips);
  chat.appendChild(wrap);
}

// ---------- setup ----------
function applyProviderStatus(prov, status, detail) {
  const st = $("st-" + prov); if (!st) return;
  switch (status) {
    case "ok": case "configured": st.className = "st ok"; st.textContent = "● configured"; break;
    case "online": case "local": st.className = "st live"; st.textContent = "● online"; break;
    case "offline": st.className = "st no"; st.textContent = "○ offline"; break;
    case "missing_key": case "not_configured": case "off": st.className = "st no"; st.textContent = "○ not configured"; break;
    case "err": st.className = "st err"; st.textContent = "✕ " + (detail || "error"); break;
    default: if (status) { st.className = "st no"; st.textContent = "○ " + status; }
  }
  refreshBrand();
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

  // setup inner tabs: Settings | Plugins
  $$(".s-tab").forEach((t) => t.onclick = () => {
    $$(".s-tab").forEach((x) => x.classList.toggle("on", x === t));
    $$(".s-pane").forEach((p) => { p.hidden = p.dataset.pane !== t.dataset.pane; });
  });

  $("lm-detect").onclick = function () {
    this.textContent = "…";
    const url = ($("lm-url").value || "").trim();
    const mins = parseFloat($("lm-timeout").value);
    const secs = (!isNaN(mins) && mins > 0) ? String(Math.round(mins * 60)) : "";
    if (pybridge) { pybridge.set_local_config(url, secs); pybridge.list_models("LOCAL"); }
    else requestModels("LOCAL");
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
  const image = pendingImage;
  $("input").value = ""; $("input").style.height = "auto";
  pendingId = activeId;
  updateSendButton();
  window.veraChat.dispatch({ type: "user", msg: text, image: image });
  if (pybridge) {
    pybridge.set_compact(!!STATE.compact);
    pybridge.send_command(text, STATE.provider, STATE.model, STATE.mode, STATE.id,
                          image ? JSON.stringify(image) : "");
  }
  clearPendingImage();
}

// ---------- image attachment (paste / drop a reference) ----------
function setPendingImage(media_type, data) { pendingImage = { media_type, data }; renderAttach(); }
function clearPendingImage() { pendingImage = null; renderAttach(); }

function renderAttach() {
  let box = $("attach");
  if (!box) {
    box = document.createElement("div"); box.id = "attach";
    const bar = $("bar"); bar.insertBefore(box, bar.querySelector(".bar-ctl"));
  }
  box.innerHTML = "";
  if (!pendingImage) { box.style.display = "none"; return; }
  box.style.display = "flex";
  const img = document.createElement("img"); img.className = "attach-thumb";
  img.src = "data:" + pendingImage.media_type + ";base64," + pendingImage.data;
  const x = document.createElement("button"); x.className = "attach-x"; x.textContent = "✕"; x.title = "Remove";
  x.onclick = clearPendingImage;
  const lbl = document.createElement("span"); lbl.className = "attach-lbl"; lbl.textContent = "reference attached";
  box.appendChild(img); box.appendChild(lbl); box.appendChild(x);
}

function fileToImage(file) {
  if (!file || !/^image\//.test(file.type || "")) return;
  const reader = new FileReader();
  reader.onload = () => {
    const m = /^data:(image\/[\w.+-]+);base64,(.*)$/.exec(String(reader.result));
    if (m) {
      let mt = m[1] === "image/jpg" ? "image/jpeg" : m[1];
      if (mt !== "image/png" && mt !== "image/jpeg") mt = "image/png";
      setPendingImage(mt, m[2]);
    }
  };
  reader.readAsDataURL(file);
}

function doStop() {
  if (pybridge) pybridge.stop();
  // the backend emits a final {status:"stopped"} which clears the running state
}

// The send button doubles as a Stop button while THIS tab is running.
function updateSendButton() {
  const btn = $("send"); if (!btn) return;
  const running = pendingId !== null && pendingId === activeId;
  btn.classList.toggle("stop", running);
  btn.textContent = running ? "■" : "➤";
  btn.title = running ? "Stop" : "Send";
}

function wireInput() {
  $("send").onclick = () => {
    (pendingId !== null && pendingId === activeId) ? doStop() : sendCurrent();
  };
  $("input").addEventListener("keydown", (ev) => {
    if (slashOpen()) {
      if (ev.key === "ArrowDown") { ev.preventDefault(); slashMove(1); return; }
      if (ev.key === "ArrowUp") { ev.preventDefault(); slashMove(-1); return; }
      if (ev.key === "Escape") { ev.preventDefault(); closeSlash(); return; }
      if (ev.key === "Tab" || (ev.key === "Enter" && slashState && slashState.level === 1)) { ev.preventDefault(); slashSelect(); return; }
    }
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendCurrent(); }
  });
  $("input").addEventListener("input", function () {
    this.style.height = "auto"; this.style.height = Math.min(this.scrollHeight, 120) + "px";
    refreshSlash();
  });
  $("input").addEventListener("blur", () => setTimeout(closeSlash, 150));

  // paste an image into the input
  $("input").addEventListener("paste", (ev) => {
    const items = (ev.clipboardData && ev.clipboardData.items) || [];
    for (const it of items) {
      if (it.type && it.type.startsWith("image/")) { fileToImage(it.getAsFile()); ev.preventDefault(); break; }
    }
  });
  // drag & drop an image onto the dock
  const bar = $("bar");
  bar.addEventListener("dragover", (ev) => { ev.preventDefault(); bar.classList.add("drag"); });
  bar.addEventListener("dragleave", () => bar.classList.remove("drag"));
  bar.addEventListener("drop", (ev) => {
    ev.preventDefault(); bar.classList.remove("drag");
    const f = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
    if (f) fileToImage(f);
  });
}

// ============================================================================
// boot
// ============================================================================
function boot() {
  wireControls();
  wireInput();
  // reverse infinite scroll: near the top, load the previous chunk of turns
  $("chat").addEventListener("scroll", () => {
    if ($("chat").scrollTop < 40 && windowFromTurn > 0) loadEarlier();
  });
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
      pybridge.get_local_config();
      pybridge.plugins();
      pybridge.commands();
    });
  } else {
    requestModels("LOCAL");
  }
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
