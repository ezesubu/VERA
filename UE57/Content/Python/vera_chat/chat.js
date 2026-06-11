"use strict";

const AGENTS = ["Manager", "Architect", "Python", "Blueprint", "QA",
                "Perception", "Critic", "Git", "LogQA"];
let pybridge = null;          // objeto Python via QWebChannel (null en dev.html)
let currentTimeline = null;   // burbuja vera en curso (timeline activa)

// ---------- helpers ----------
const $ = (id) => document.getElementById(id);

function scrollBottom() { const c = $("chat"); c.scrollTop = c.scrollHeight; }

function md(text) {
  const html = marked.parse(text || "");
  const div = document.createElement("div");
  div.className = "md";
  div.innerHTML = html;
  div.querySelectorAll("pre code").forEach((el) => hljs.highlightElement(el));
  return div;
}

function bubble(cls) {
  const b = document.createElement("div");
  b.className = "bubble " + cls;
  $("chat").appendChild(b);
  return b;
}

function ensureTimeline() {
  if (!currentTimeline) currentTimeline = bubble("vera");
  return currentTimeline;
}

// ---------- chips ----------
function renderChips(working) {
  const chips = $("chips");
  chips.innerHTML = "";
  for (const a of AGENTS.slice(0, 5)) {
    const s = document.createElement("span");
    s.className = "chip" + (a === working ? " working" : "");
    s.textContent = a + (a === working ? " ●" : "");
    chips.appendChild(s);
  }
  const more = document.createElement("span");
  more.className = "chip";
  more.textContent = "+" + (AGENTS.length - 5);
  chips.appendChild(more);
}

// ---------- dispatch (único punto de entrada Python→JS) ----------
window.veraChat = {
  dispatch(e) {
    switch (e.type) {
      case "user": {
        currentTimeline = null;
        bubble("user").textContent = e.msg;
        renderChips("Manager");
        break;
      }
      case "progress": {
        const tl = ensureTimeline();
        tl.querySelectorAll(".tl-item.working")
          .forEach((el) => el.classList.remove("working"));
        const item = document.createElement("div");
        item.className = "tl-item working";
        item.innerHTML = "<b>" + e.agent + "</b> — " + e.msg;
        tl.appendChild(item);
        renderChips(e.agent);
        break;
      }
      case "image": {
        const img = document.createElement("img");
        img.className = "shot";
        img.src = "file:///" + String(e.path).replace(/\\/g, "/");
        img.onclick = () => pybridge && pybridge.open_image(e.path);
        ensureTimeline().appendChild(img);
        break;
      }
      case "final": {
        const tl = ensureTimeline();
        tl.querySelectorAll(".tl-item.working")
          .forEach((el) => el.classList.remove("working"));
        tl.appendChild(md(e.msg));
        if (e.status === "error") tl.classList.add("error");
        currentTimeline = null;
        renderChips(null);
        break;
      }
      case "error": {
        bubble("error").appendChild(md(e.msg));
        break;
      }
      case "interrupted": {
        const tl = ensureTimeline();
        const items = tl.querySelectorAll(".tl-item.working");
        items.forEach((el) => { el.classList.remove("working");
                                el.classList.add("interrupted"); });
        const note = document.createElement("div");
        note.className = "tl-item interrupted";
        note.textContent = "interrumpido — el backend dejó de responder";
        tl.appendChild(note);
        currentTimeline = null;
        renderChips(null);
        break;
      }
      case "status": {
        const st = $("status");
        st.textContent = e.online ? ("● Online · " + (e.version || "UE")) : "● Offline";
        st.className = e.online ? "" : "off";
        break;
      }
      case "history": {
        (e.events || []).forEach((ev) => window.veraChat.dispatch(ev));
        break;
      }
    }
    scrollBottom();
  },
};

// ---------- input ----------
function sendCurrent() {
  const text = $("input").value.trim();
  if (!text) return;
  $("input").value = "";
  $("input").style.height = "auto";
  window.veraChat.dispatch({ type: "user", msg: text });
  if (pybridge) pybridge.send_command(text);
}

$("send").onclick = sendCurrent;
$("input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendCurrent(); }
});
$("input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 110) + "px";
});

// Mic: solo estados visuales en esta iteración (Whisper = iteración aparte)
$("mic").onclick = function () { this.classList.toggle("recording"); };

// ---------- QWebChannel (ausente en dev.html → modo standalone) ----------
if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    pybridge = channel.objects.pybridge;
    pybridge.js_ready();
  });
}

renderChips(null);
