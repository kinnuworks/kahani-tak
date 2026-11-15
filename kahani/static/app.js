// Kahani Tak parent loop: record a child reading one card, show marked words, follow the ASER path.
const $ = (id) => document.getElementById(id);
const LEVEL_HI = { beginner: "अभी अक्षर सीख रहा है", letter: "अक्षर", word: "शब्द", paragraph: "अनुच्छेद", story: "कहानी" };
const LADDER = ["letter", "word", "paragraph", "story"];
const STEP_HI = {
  paragraph: "यह अनुच्छेद बच्चा ज़ोर से पढ़े",
  story: "बहुत अच्छा! अब यह कहानी पढ़े",
  word: "अब ये शब्द पढ़े",
  letter: "अब ये अक्षर पढ़े",
};
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode: key lives for this visit only */ } },
};
let childKey = store.get("kt_child") || newKey();
let session = null, level = null, card = null, rec = null, chunks = [], lastFinal = null, pollTimer = null;
const params = new URLSearchParams(location.search);
const teacherCode = params.get("t");
const cardSet = params.get("set");   // demos and tests can fix the card set, e.g. ?set=A
const previewState = params.get("state");   // ?state=... shows one screen with example data (design work)
const MSG = {
  mic: "माइक की अनुमति नहीं मिली। ब्राउज़र में ऊपर ताले 🔒 पर दबाकर माइक्रोफ़ोन चालू करें।",
  nothing: "आवाज़ साफ़ नहीं आई। फ़ोन बच्चे के पास रखें और एक बार फिर पढ़वाएँ।",
  network: "इंटरनेट से जुड़ नहीं पाया। फिर कोशिश करें।",
  server: (code) => "जाँच नहीं हो पाई (" + code + ")। फिर कोशिश करें।",
};

function newKey() { const k = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2)); store.set("kt_child", k); return k; }
function show(id) { for (const s of document.querySelectorAll(".screen")) s.hidden = s.id !== id; window.scrollTo(0, 0); }
function renderCard(el, c) {
  el.innerHTML = "";
  if (Array.isArray(c)) { el.classList.add("items"); c.forEach((w) => { const s = document.createElement("span"); s.textContent = w; el.appendChild(s); }); }
  else { el.classList.remove("items"); c.split("।").filter((x) => x.trim()).forEach((line) => { const p = document.createElement("p"); p.textContent = line.trim() + "।"; el.appendChild(p); }); }
}
function err(msg) { const e = $("error"); e.textContent = msg; e.hidden = !msg; }

if (teacherCode) { $("teacher-note").hidden = false; $("teacher-note").textContent = "आपके बच्चे की टीचर इस जाँच को देख सकेंगी (कोड " + teacherCode.toUpperCase() + ")।"; }
$("consent").addEventListener("change", () => { $("consent").closest("label").classList.remove("kt-need"); });

$("begin").addEventListener("click", () => show("setup"));
$("go").addEventListener("click", async () => {
  if (!$("consent").checked) { const l = $("consent").closest("label"); l.classList.add("kt-need"); l.scrollIntoView({ block: "center" }); $("consent").focus(); return; }
  $("go").disabled = true;
  const r = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ klass: +$("klass").value, consent: true, child_key: childKey, teacher_code: teacherCode, set_id: cardSet }) });
  $("go").disabled = false;
  if (!r.ok) { alert("शुरू नहीं हो पाया, फिर कोशिश करें।"); return; }
  session = await r.json();
  goRead(session.level, session.card);
});

function goRead(lv, c) {
  level = lv; card = c; err("");
  $("step-label").textContent = STEP_HI[lv];
  renderCard($("card"), c);
  $("rec").textContent = "🎤 बच्चे से पढ़वाइए"; $("rec").disabled = false; $("rec").classList.remove("on");
  $("rec-status").textContent = "बटन दबाएँ, बच्चा पढ़े, फिर दोबारा दबाएँ।";
  show("read");
}

function pickMime() {
  const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  return (window.MediaRecorder && types.find((t) => MediaRecorder.isTypeSupported(t))) || "";
}

$("rec").addEventListener("click", async () => {
  if (rec && rec.state === "recording") { rec.stop(); return; }
  err("");
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { err(MSG.mic); return; }
  const mime = pickMime();
  rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  chunks = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.onstop = () => { stream.getTracks().forEach((t) => t.stop()); send(new Blob(chunks, { type: rec.mimeType || mime || "audio/webm" })); };
  rec.start();
  $("rec").textContent = "⏹ पढ़ना हो गया"; $("rec").classList.add("on");
  $("rec-status").textContent = "सुन रहे हैं… बच्चा पूरा पढ़ ले, फिर दबाएँ।";
});

async function send(blob) {
  $("rec").disabled = true; $("rec").classList.remove("on");
  $("rec-status").textContent = "जाँच रहे हैं… (लगभग आधा मिनट)";
  const fd = new FormData();
  fd.append("session_id", session.session_id); fd.append("level", level);
  fd.append("audio", blob, "reading." + (blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm"));
  let r;
  try { r = await fetch("/api/read", { method: "POST", body: fd }); }
  catch (e) { $("rec").disabled = false; $("rec").textContent = "🎤 फिर से पढ़वाइए"; err(MSG.network); return; }
  const data = await r.json().catch(() => ({}));
  if (r.status === 422) { $("rec").disabled = false; $("rec").textContent = "🎤 फिर से पढ़वाइए"; err(MSG.nothing); return; }
  if (!r.ok) { $("rec").disabled = false; $("rec").textContent = "🎤 फिर से पढ़वाइए"; err(MSG.server(r.status)); return; }
  showResult(data);
}

function showResult(d) {
  const m = $("marked"); m.innerHTML = "";
  d.words.forEach((w) => { const s = document.createElement("span"); s.textContent = w.text; s.className = w.ok ? "ok" : "bad"; m.appendChild(s); m.appendChild(document.createTextNode(" ")); });
  const n = d.mistakes;
  $("verdict").textContent = (n === 0 ? "सब शब्द ठीक पढ़े।" : n + " शब्द छूटे या गलत पढ़े (लाल)।") + (d.needs_teacher && d.teacher_linked ? " टीचर इसे एक बार सुनकर पक्का करेंगी।" : "");
  if (d.final_level) { $("next").hidden = true; setTimeout(() => showFinal(d), 2500); }
  else { $("next").hidden = false; $("next").onclick = () => goRead(d.next_level, d.next_card); }
  show("result");
}

function showFinal(d) {
  lastFinal = d;
  const lv = d.final_level;
  $("final-line").textContent = lv === "beginner" ? "बच्चा अभी अक्षर पहचानना सीख रहा है" : "बच्चा " + LEVEL_HI[lv] + " तक पढ़ लेता है";
  const ol = $("ladder"); ol.innerHTML = "";
  LADDER.forEach((s) => { const li = document.createElement("li"); li.textContent = LEVEL_HI[s]; if (LADDER.indexOf(s) <= LADDER.indexOf(lv)) li.className = "reached"; if (s === lv) li.className = "here"; ol.appendChild(li); });
  const p = d.practice;
  const pr = $("practice"); pr.innerHTML = "";
  const h = document.createElement("h3"); h.textContent = "आज रात " + p.minutes + " मिनट: " + p.focus; pr.appendChild(h);
  const how = document.createElement("p"); how.textContent = p.how; pr.appendChild(how);
  const c = document.createElement("div"); c.className = "card"; renderCard(c, p.items); pr.appendChild(c);
  $("speak").hidden = !("speechSynthesis" in window);
  $("practise-now").hidden = !session;
  show("final");
  watchTeacher();
}

function watchTeacher() {
  clearInterval(pollTimer);
  if (previewState || !session) return;
  const t = $("teacher-status");
  const tick = async () => {
    const r = await fetch("/api/session/" + session.session_id).catch(() => null);
    if (!r || !r.ok) return;
    const s = await r.json();
    if (s.waiting_for_teacher) { t.hidden = false; t.textContent = "⏳ टीचर अभी जाँच रही हैं। यह पेज खुला रखें, अपने आप बदल जाएगा।"; }
    else if (s.teacher_checked) {
      t.hidden = false; t.textContent = "✅ टीचर ने जाँच लिया।";
      clearInterval(pollTimer);
      if (s.final_level && s.final_level !== lastFinal.final_level) showFinal({ ...lastFinal, final_level: s.final_level, practice: s.practice });
    } else { t.hidden = true; clearInterval(pollTimer); }
  };
  tick(); pollTimer = setInterval(tick, 10000);
}

$("speak").addEventListener("click", () => {
  const u = new SpeechSynthesisUtterance($("final-line").textContent + "। " + $("practice").querySelector("p").textContent);
  u.lang = "hi-IN"; speechSynthesis.cancel(); speechSynthesis.speak(u);
});
$("again").addEventListener("click", () => { childKey = newKey(); clearInterval(pollTimer); session = null; $("consent").checked = false; show("start"); });

// ---------- first-screen example: a real result of this app on a synthetic voice ----------
if (!$("example").dataset.filled) fetch("/static/example.json").then((r) => r.json()).then((ex) => {
  const box = $("example"), m = box.querySelector(".marked");
  ex.words.forEach((w) => { const sp = document.createElement("span"); sp.textContent = w.text; sp.className = w.ok ? "ok" : "bad"; m.append(sp, " "); });
  $("example-line").textContent = ex.mistakes + " शब्द छूटे (हाइलाइट)। ASER के नियम से 3 तक गलती पर अनुच्छेद पास, पर गिनती सीमा के पास है, इसलिए टीचर सुनकर पक्का करेंगी।";
  box.hidden = false;
}).catch(() => { /* example is optional; the check still works */ });

// ---------- ?state= previews ----------
async function preview(state) {
  $("preview-banner").hidden = false; $("preview-name").textContent = state;
  const d = await (await fetch("/api/preview")).json();
  const ex = await (await fetch("/static/example.json")).json();
  const c = d.cards;
  const fin = (lv, extra = {}) => showFinal({ final_level: lv, practice: d.practice[lv], ...extra });
  const statusLine = (txt) => { $("teacher-status").hidden = false; $("teacher-status").textContent = txt; };
  const views = {
    start: () => show("start"),
    setup: () => show("setup"),
    practise: () => { renderCard($("p-card"), d.practice.paragraph.items); $("p-level").textContent = "बच्चा अनुच्छेद तक पढ़ लेता है · अभ्यास: कहानी"; show("practise"); },
    "practise-result": () => { renderCard($("p-card"), d.practice.paragraph.items); show("practise"); showPractice({ words: d.practice.paragraph.items.replace(/।/g, " ").split(/\s+/).filter(Boolean).map((t, i) => ({ text: t, ok: i % 9 !== 4 })), mistakes: 0, previous_mistakes: [] }); $("p-verdict").textContent = "उदाहरण: हाइलाइट शब्द पर फिर से ध्यान दें।"; },
    read: () => goRead("paragraph", c.paragraph),
    recording: () => { goRead("paragraph", c.paragraph); $("rec").textContent = "⏹ पढ़ना हो गया"; $("rec").classList.add("on"); $("rec-status").textContent = "सुन रहे हैं… बच्चा पूरा पढ़ ले, फिर दबाएँ।"; },
    checking: () => { goRead("paragraph", c.paragraph); $("rec").disabled = true; $("rec-status").textContent = "जाँच रहे हैं… (लगभग आधा मिनट)"; },
    "result-pass": () => showResult({ words: c.paragraph.replace(/।/g, " ").split(/\s+/).filter(Boolean).map((t) => ({ text: t, ok: true })), mistakes: 0, needs_teacher: false, teacher_linked: false, final_level: null, next_level: "story", next_card: c.story }),
    "result-teacher": () => showResult({ ...ex, teacher_linked: true, final_level: null, next_level: "story", next_card: c.story }),
    "final-story": () => fin("story"), "final-paragraph": () => fin("paragraph"), "final-word": () => fin("word"),
    "final-letter": () => fin("letter"), "final-beginner": () => fin("beginner"),
    "final-waiting": () => { fin("paragraph"); statusLine("⏳ टीचर अभी जाँच रही हैं। यह पेज खुला रखें, अपने आप बदल जाएगा।"); },
    "final-checked": () => { fin("paragraph"); statusLine("✅ टीचर ने जाँच लिया।"); },
    "error-mic": () => { goRead("paragraph", c.paragraph); err(MSG.mic); },
    "error-nothing-heard": () => { goRead("paragraph", c.paragraph); err(MSG.nothing); },
    "error-network": () => { goRead("paragraph", c.paragraph); err(MSG.network); },
    "error-server": () => { goRead("paragraph", c.paragraph); err(MSG.server(503)); },
  };
  (views[state] || views.start)();
  if (state === "result-pass" || state === "result-teacher") $("next").onclick = null;
  if (state.startsWith("final")) $("practise-now").hidden = false;
}
if (previewState) preview(previewState);

// ---------- practise tonight: the child reads the practice card, every word is marked again ----------
let pRec = null, pChunks = [];
function markInto(el, words) {
  el.innerHTML = "";
  words.forEach((w) => { const sp = document.createElement("span"); sp.textContent = w.text; sp.className = w.ok ? "ok" : "bad"; el.append(sp, " "); });
  el.hidden = false;
}
$("practise-now").addEventListener("click", async () => {
  const r = await fetch("/api/practice/" + session.session_id);
  if (!r.ok) return;
  const c = await r.json();
  renderCard($("p-card"), c.items);
  $("p-level").textContent = $("final-line").textContent + " · अभ्यास: " + c.focus;
  $("p-listen").hidden = !("speechSynthesis" in window);
  $("p-marked").hidden = true; $("p-verdict").textContent = ""; $("p-again").hidden = true;
  $("p-rec").hidden = false; $("p-rec").disabled = false; $("p-rec").textContent = "🎤 बच्चे से पढ़वाइए";
  $("p-status").textContent = "बटन दबाएँ, बच्चा पढ़े, फिर दोबारा दबाएँ।";
  show("practise");
});
$("p-rec").addEventListener("click", async () => {
  if (pRec && pRec.state === "recording") { pRec.stop(); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { $("p-status").textContent = MSG.mic; return; }
  const mime = pickMime();
  pRec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined); pChunks = [];
  pRec.ondataavailable = (e) => e.data.size && pChunks.push(e.data);
  pRec.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    $("p-rec").disabled = true; $("p-status").textContent = "जाँच रहे हैं…";
    const blob = new Blob(pChunks, { type: pRec.mimeType || mime || "audio/webm" });
    const fd = new FormData(); fd.append("session_id", session.session_id); fd.append("audio", blob, "practice.webm");
    const r = await fetch("/api/practice", { method: "POST", body: fd }).catch(() => null);
    $("p-rec").disabled = false; $("p-rec").textContent = "🎤 फिर से पढ़वाइए";
    if (!r || !r.ok) { $("p-status").textContent = r && r.status === 422 ? MSG.nothing : MSG.network; return; }
    showPractice(await r.json());
  };
  pRec.start(); $("p-rec").textContent = "⏹ पढ़ना हो गया"; $("p-status").textContent = "सुन रहे हैं…";
});
function showPractice(d) {
  markInto($("p-marked"), d.words);
  const prev = d.previous_mistakes && d.previous_mistakes.length ? d.previous_mistakes[d.previous_mistakes.length - 1] : null;
  $("p-verdict").textContent = (d.mistakes === 0 ? "सब शब्द ठीक पढ़े! " : d.mistakes + " शब्द पर फिर से ध्यान दें (हाइलाइट)। ") +
    (prev !== null ? "पिछली बार " + prev + " गलती थी, इस बार " + d.mistakes + "।" : "");
  $("p-status").textContent = ""; $("p-again").hidden = false; $("p-rec").hidden = true;
}
$("p-again").addEventListener("click", () => { $("p-rec").hidden = false; $("p-marked").hidden = true; $("p-verdict").textContent = ""; $("p-again").hidden = true; });
$("p-done").addEventListener("click", () => show("final"));

$("p-listen").addEventListener("click", () => {
  const u = new SpeechSynthesisUtterance($("p-card").textContent);
  u.lang = "hi-IN"; u.rate = 0.8; speechSynthesis.cancel(); speechSynthesis.speak(u);
});
