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

function newKey() { const k = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2)); store.set("kt_child", k); return k; }
function show(id) { for (const s of document.querySelectorAll(".screen")) s.hidden = s.id !== id; window.scrollTo(0, 0); }
function renderCard(el, c) {
  el.innerHTML = "";
  if (Array.isArray(c)) { el.classList.add("items"); c.forEach((w) => { const s = document.createElement("span"); s.textContent = w; el.appendChild(s); }); }
  else { el.classList.remove("items"); c.split("।").filter((x) => x.trim()).forEach((line) => { const p = document.createElement("p"); p.textContent = line.trim() + "।"; el.appendChild(p); }); }
}
function err(msg) { const e = $("error"); e.textContent = msg; e.hidden = !msg; }

if (teacherCode) { $("teacher-note").hidden = false; $("teacher-note").textContent = "आपके बच्चे की टीचर इस जाँच को देख सकेंगी (कोड " + teacherCode.toUpperCase() + ")।"; }
$("consent").addEventListener("change", () => { $("begin").disabled = !$("consent").checked; });

$("begin").addEventListener("click", async () => {
  $("begin").disabled = true;
  const r = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ klass: +$("klass").value, consent: true, child_key: childKey, teacher_code: teacherCode, set_id: cardSet }) });
  $("begin").disabled = false;
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
  catch (e) { err("माइक की अनुमति नहीं मिली। ब्राउज़र में ऊपर ताले 🔒 पर दबाकर माइक्रोफ़ोन चालू करें।"); return; }
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
  catch (e) { $("rec").disabled = false; $("rec").textContent = "🎤 फिर से पढ़वाइए"; err("इंटरनेट से जुड़ नहीं पाया। फिर कोशिश करें।"); return; }
  const data = await r.json().catch(() => ({}));
  if (r.status === 422) { $("rec").disabled = false; $("rec").textContent = "🎤 फिर से पढ़वाइए"; err("आवाज़ साफ़ नहीं आई। फ़ोन बच्चे के पास रखें और एक बार फिर पढ़वाएँ।"); return; }
  if (!r.ok) { $("rec").disabled = false; $("rec").textContent = "🎤 फिर से पढ़वाइए"; err("जाँच नहीं हो पाई (" + r.status + ")। फिर कोशिश करें।"); return; }
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
  show("final");
  watchTeacher();
}

function watchTeacher() {
  clearInterval(pollTimer);
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
$("again").addEventListener("click", () => { childKey = newKey(); clearInterval(pollTimer); session = null; $("consent").checked = false; $("begin").disabled = true; show("start"); });
