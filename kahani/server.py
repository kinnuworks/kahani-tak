"""Kahani Tak web app: parent reading check, teacher confirmation, public impact counts."""
import datetime as dt
import hashlib
import json
import os
import pathlib
import secrets
import sqlite3
import tempfile
import threading
import time

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from kahani import scoring

HERE = pathlib.Path(__file__).parent
CARDS = {s["id"]: s for s in json.loads((HERE / "cards.json").read_text())["sets"]}
SET_IDS = sorted(CARDS)
LEVELS = ["beginner", "letter", "word", "paragraph", "story"]
AUDIO_KEEP_DAYS = 7
MAX_AUDIO_BYTES = 8 * 1024 * 1024
_lock = threading.Lock()
after_write = None   # set by the host (Modal) to persist the data volume


def _wrote():
    if after_write:
        after_write()


def data_dir():
    d = pathlib.Path(os.environ.get("DATA_DIR", HERE.parent / "data"))
    (d / "audio").mkdir(parents=True, exist_ok=True)
    return d


def db():
    con = sqlite3.connect(data_dir() / "kahani.db", timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript("""
    create table if not exists teachers(code text primary key, name text, created text);
    create table if not exists sessions(id text primary key, created text, klass int, child_key text,
        teacher_code text, set_id text);
    create table if not exists readings(id text primary key, session_id text, created text, level text,
        heard text, words text, mistakes int, total int, passed int, needs_teacher int, audio text,
        audio_secs real, model_secs real, teacher_words text, teacher_passed int, confirmed_at text);
    """)
    if "key_hash" not in [r[1] for r in con.execute("pragma table_info(teachers)")]:
        con.execute("alter table teachers add column key_hash text")
    if "is_test" not in [r[1] for r in con.execute("pragma table_info(sessions)")]:
        con.execute("alter table sessions add column is_test int default 0")
    return con


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def card_for(set_id, level):
    return CARDS[set_id][level] if level in ("letter", "word", "paragraph", "story") else None


def load_transcriber():
    from kahani.asr import Transcriber
    return Transcriber()


app = FastAPI(title="Kahani Tak")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


# ---------- pages ----------
def page(name):
    return HTMLResponse((HERE / "static" / name).read_text(encoding="utf-8"))


@app.get("/")
def parent_page():
    return page("index.html")


@app.get("/teacher")
@app.get("/teacher/{code}")
def teacher_page(code: str = ""):
    return page("teacher.html")


@app.get("/impact")
def impact_page():
    return page("impact.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "model_loaded": getattr(app.state, "transcriber", None) is not None}


# ---------- parent loop ----------
class SessionIn(BaseModel):
    klass: int
    consent: bool
    child_key: str
    teacher_code: str | None = None
    set_id: str | None = None


def is_test_request(token):
    """Our own automated checks send X-Test-Token; those sessions never count as impact."""
    want = os.environ.get("TEST_TOKEN", "")
    return bool(want) and bool(token) and secrets.compare_digest(token, want)


@app.post("/api/session")
def new_session(body: SessionIn, x_test_token: str | None = Header(default=None)):
    if not body.consent:
        raise HTTPException(400, "parent consent is required")
    if not (1 <= body.klass <= 8) or not (4 <= len(body.child_key) <= 64):
        raise HTTPException(400, "bad class or child key")
    con = db()
    teacher = None
    if body.teacher_code:
        row = con.execute("select code from teachers where code=?", (body.teacher_code.upper(),)).fetchone()
        teacher = row["code"] if row else None
    if body.set_id in CARDS:
        set_id = body.set_id
    else:   # a different card set each time the same child is checked again
        n = con.execute("select count(*) from sessions where child_key=?", (body.child_key,)).fetchone()[0]
        set_id = SET_IDS[(n + int(secrets.randbelow(len(SET_IDS)) if n == 0 else 0)) % len(SET_IDS)]
    sid = secrets.token_urlsafe(12)
    with _lock, con:
        con.execute("insert into sessions(id,created,klass,child_key,teacher_code,set_id,is_test) values(?,?,?,?,?,?,?)",
                    (sid, now(), body.klass, body.child_key, teacher, set_id, int(is_test_request(x_test_token))))
    _wrote()
    return {"session_id": sid, "set_id": set_id, "level": "paragraph", "card": card_for(set_id, "paragraph"),
            "teacher_linked": teacher is not None}


def _effective(r):
    if r["confirmed_at"]:
        return json.loads(r["teacher_words"]), bool(r["teacher_passed"])
    return json.loads(r["words"]), bool(r["passed"])


def session_state(con, sid):
    s = con.execute("select * from sessions where id=?", (sid,)).fetchone()
    if not s:
        raise HTTPException(404, "no such session")
    rows = con.execute("select * from readings where session_id=? order by created, rowid", (sid,)).fetchall()
    expected, final, done = "paragraph", None, []
    for r in rows:
        words, passed = _effective(r)
        if r["level"] != expected:         # a teacher's correction changed the path: stop at what is proven
            break
        expected, final = scoring.next_step(r["level"], passed)
        done.append({"reading_id": r["id"], "level": r["level"], "passed": passed, "words": words,
                     "mistakes": sum(not w["ok"] for w in words), "needs_teacher": bool(r["needs_teacher"]),
                     "teacher_checked": r["confirmed_at"] is not None})
        if final:
            break
    pending = any(d["needs_teacher"] and not d["teacher_checked"] for d in done) and s["teacher_code"] is not None
    return {"session_id": sid, "set_id": s["set_id"], "readings": done, "next_level": None if final else expected,
            "next_card": None if final else card_for(s["set_id"], expected), "final_level": final,
            "teacher_linked": s["teacher_code"] is not None, "waiting_for_teacher": pending,
            "teacher_checked": any(d["teacher_checked"] for d in done),
            "practice": practice_for(final or _floor(done), s["set_id"])}


def _floor(done):
    passed = [d["level"] for d in done if d["passed"]]
    return passed[-1] if passed else "beginner"


def practice_for(level, set_id):
    other = CARDS[SET_IDS[(SET_IDS.index(set_id) + 1) % len(SET_IDS)]]
    plan = {
        "beginner": ("अक्षर", other["letter"], "हर अक्षर पर उँगली रखकर उसकी आवाज़ बोलें। बच्चा आपके बाद दोहराए।"),
        "letter": ("शब्द", other["word"], "हर शब्द के अक्षर अलग-अलग बोलें, फिर पूरा शब्द साथ में पढ़ें।"),
        "word": ("वाक्य", other["paragraph"], "एक वाक्य आप पढ़ें, वही वाक्य बच्चा पढ़े। हर दिन एक वाक्य और।"),
        "paragraph": ("कहानी", other["story"], "रोज़ दो वाक्य बच्चा पढ़े। अटकने पर शब्द बताएँ, डाँटें नहीं।"),
        "story": ("कहानी", other["story"], "बच्चा कहानी पढ़कर सुनाए, फिर पूछें: आगे क्या हुआ होगा?"),
    }[level]
    return {"focus": plan[0], "items": plan[1], "how": plan[2], "minutes": 5}


@app.post("/api/read")
async def read(session_id: str = Form(...), level: str = Form(...), audio: UploadFile = File(...)):
    con = db()
    st = session_state(con, session_id)
    if st["final_level"] or level != st["next_level"]:
        raise HTTPException(409, f"expected level {st['next_level']}")
    blob = await audio.read()
    if not blob or len(blob) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "recording too large or empty")
    rid = secrets.token_urlsafe(10)
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/wav": "wav", "audio/x-wav": "wav",
           "audio/mpeg": "mp3", "audio/aac": "aac"}.get((audio.content_type or "").split(";")[0], "bin")
    path = data_dir() / "audio" / f"{rid}.{ext}"
    path.write_bytes(blob)
    t0 = time.time()
    try:
        from kahani.asr import decode_audio
        samples = decode_audio(path)
        heard, secs = app.state.transcriber.transcribe(samples)
        result = scoring.score_reading(level, card_for(st["set_id"], level), heard)
    except scoring.NothingHeard:
        path.unlink(missing_ok=True)
        raise HTTPException(422, {"code": "nothing_heard", "message": "आवाज़ साफ़ नहीं आई"})
    except Exception as e:  # decoding failures are reported, never turned into a result
        path.unlink(missing_ok=True)
        raise HTTPException(422, {"code": "bad_audio", "message": str(e)[:200]})
    unsure = scoring.needs_teacher(level, result["mistakes"])
    with _lock, con:
        con.execute("insert into readings(id,session_id,created,level,heard,words,mistakes,total,passed,needs_teacher,"
                    "audio,audio_secs,model_secs) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, session_id, now(), level, heard, json.dumps(result["words"], ensure_ascii=False),
                     result["mistakes"], result["total"], int(result["passed"]), int(unsure), str(path), secs,
                     round(time.time() - t0, 2)))
    _wrote()
    st = session_state(con, session_id)
    return {"reading_id": rid, "level": level, "words": result["words"], "mistakes": result["mistakes"],
            "passed": result["passed"], "needs_teacher": unsure, "heard": heard,
            "next_level": st["next_level"], "next_card": st["next_card"], "final_level": st["final_level"],
            "practice": st["practice"], "teacher_linked": st["teacher_linked"]}


@app.get("/api/session/{sid}")
def get_session(sid: str):
    return session_state(db(), sid)


# ---------- teacher ----------
class TeacherIn(BaseModel):
    name: str


@app.post("/api/teacher")
def new_teacher(body: TeacherIn):
    """Class code: public, goes in the parent link. Teacher key: secret, shown once, stored only as a hash."""
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    key = secrets.token_urlsafe(32)
    con = db()
    with _lock, con:
        con.execute("insert into teachers(code,name,created,key_hash) values(?,?,?,?)",
                    (code, body.name.strip()[:60], now(), _hash(key)))
    _wrote()
    return {"code": code, "key": key, "name": body.name.strip()[:60]}


def _hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def _teacher(con, code, key):
    """Every teacher action needs the secret key for this class; the class code alone is refused."""
    row = con.execute("select * from teachers where code=?", (code.upper(),)).fetchone()
    if not row or not key or not row["key_hash"] or not secrets.compare_digest(_hash(key), row["key_hash"]):
        raise HTTPException(403, "teacher key required")
    return row


def _items(con, code, only_open):
    q = ("select r.*, s.set_id, s.klass from readings r join sessions s on s.id=r.session_id where s.teacher_code=? "
         + ("and r.needs_teacher=1 and r.confirmed_at is null " if only_open else "") + "order by r.created desc limit 200")
    out = []
    for r in con.execute(q, (code.upper(),)):
        words, passed = _effective(r)
        out.append({"reading_id": r["id"], "created": r["created"], "level": r["level"], "klass": r["klass"],
                    "words": words, "passed": passed, "mistakes": sum(not w["ok"] for w in words),
                    "confirmed": r["confirmed_at"] is not None, "has_audio": bool(r["audio"])})
    return out


@app.get("/api/teacher/{code}/queue")
def teacher_queue(code: str, x_teacher_key: str | None = Header(default=None)):
    con = db(); t = _teacher(con, code, x_teacher_key)
    return {"name": t["name"], "items": _items(con, code, True)}


@app.get("/api/teacher/{code}/all")
def teacher_all(code: str, x_teacher_key: str | None = Header(default=None)):
    con = db(); t = _teacher(con, code, x_teacher_key)
    return {"name": t["name"], "items": _items(con, code, False)}


@app.get("/api/teacher/{code}/audio/{rid}")
def teacher_audio(code: str, rid: str, x_teacher_key: str | None = Header(default=None)):
    con = db(); _teacher(con, code, x_teacher_key)
    r = con.execute("select r.audio, r.confirmed_at from readings r join sessions s on s.id=r.session_id "
                    "where r.id=? and s.teacher_code=?", (rid, code.upper())).fetchone()
    if not r:
        raise HTTPException(404, "not found")
    if not r["audio"] or not pathlib.Path(r["audio"]).exists():
        raise HTTPException(410, "recording deleted after checking")
    return FileResponse(r["audio"])


class ConfirmIn(BaseModel):
    reading_id: str
    wrong: list[int]


@app.post("/api/teacher/{code}/confirm")
def teacher_confirm(code: str, body: ConfirmIn, x_teacher_key: str | None = Header(default=None)):
    con = db(); _teacher(con, code, x_teacher_key)
    r = con.execute("select r.* from readings r join sessions s on s.id=r.session_id where r.id=? and s.teacher_code=?",
                    (body.reading_id, code.upper())).fetchone()
    if not r:
        raise HTTPException(404, "not found")
    words = json.loads(r["words"])
    if any(i < 0 or i >= len(words) for i in body.wrong):
        raise HTTPException(400, "bad word index")
    fixed = [{"text": w["text"], "ok": i not in body.wrong} for i, w in enumerate(words)]
    mistakes = len(set(body.wrong))
    passed = (len(fixed) - mistakes) >= scoring.ITEMS_TO_PASS if r["level"] in ("letter", "word") \
        else mistakes <= scoring.PASS_MAX_MISTAKES
    if r["audio"]:
        pathlib.Path(r["audio"]).unlink(missing_ok=True)
    with _lock, con:
        con.execute("update readings set teacher_words=?, teacher_passed=?, confirmed_at=?, audio=null where id=?",
                    (json.dumps(fixed, ensure_ascii=False), int(passed), now(), body.reading_id))
    _wrote()
    return {"reading_id": body.reading_id, "passed": passed, "mistakes": mistakes, "model_passed": bool(r["passed"])}


class PlanIn(BaseModel):
    prompt: str | None = None


def class_data(con, code):
    """Children of one class (latest finished check each), anonymous labels, waiting count, missed words."""
    from kahani.agent import ClassData
    import collections
    sessions = con.execute("select id, child_key from sessions where teacher_code=? order by created", (code.upper(),)).fetchall()
    latest, missed = {}, collections.defaultdict(collections.Counter)
    words_by_child = collections.defaultdict(list)
    for srow in sessions:
        st = session_state(con, srow["id"])
        if st["final_level"]:
            latest[srow["child_key"]] = (st["final_level"], st["teacher_checked"])
        for rd in st["readings"]:
            words_by_child[srow["child_key"]] += [w["text"] for w in rd["words"] if not w["ok"]]
    children = []
    for i, (ck, (lv, checked)) in enumerate(latest.items(), 1):
        children.append({"label": f"बच्चा {i}", "level": lv, "teacher_checked": checked})
        missed[lv].update(words_by_child[ck])
    waiting = con.execute("select count(*) from readings r join sessions s on s.id=r.session_id where s.teacher_code=? "
                          "and r.needs_teacher=1 and r.confirmed_at is null", (code.upper(),)).fetchone()[0]
    cards = CARDS[SET_IDS[0]]
    return ClassData(children, waiting, missed, {"letter": cards["letter"], "word": cards["word"],
                                                 "paragraph": cards["paragraph"], "story": cards["story"]})


@app.post("/api/teacher/{code}/plan")
def teacher_plan(code: str, body: PlanIn, x_teacher_key: str | None = Header(default=None)):
    """The class-planner agent (also registered in AgentFoundry's Agent Studio; invoked there over HTTP)."""
    from kahani import agent
    con = db(); _teacher(con, code, x_teacher_key)
    try:
        return agent.plan(class_data(con, code), body.prompt or "")
    except agent.PlannerUnavailable as e:
        raise HTTPException(503, {"code": "planner_unavailable", "message": str(e)})


# ---------- impact ----------
@app.get("/api/impact")
def impact():
    con = db()
    sessions = [r["id"] for r in con.execute("select id from sessions where is_test=0 and id in (select session_id from readings)")]
    levels = {k: 0 for k in LEVELS}
    for sid in sessions:
        f = session_state(con, sid)["final_level"]
        if f:
            levels[f] += 1
    one = lambda q: con.execute(q).fetchone()[0]
    R = "(select r.* from readings r join sessions s on s.id=r.session_id where s.is_test=0)"
    checked = one(f"select count(*) from {R} where confirmed_at is not null")
    agree = one(f"select count(*) from {R} where confirmed_at is not null and teacher_passed=passed")
    return {"children_checked": one("select count(distinct child_key) from sessions where is_test=0 and id in (select session_id from readings)"),
            "checks_finished": sum(levels.values()), "readings": one(f"select count(*) from {R}"),
            "levels": levels, "teacher_checked": checked, "teacher_agreed": agree,
            "rechecked_children": one("select count(*) from (select child_key from sessions where is_test=0 and id in "
                                      "(select session_id from readings) group by child_key having count(*)>1)"),
            "teachers": one("select count(distinct teacher_code) from sessions where is_test=0 and teacher_code is not null"),
            "median_model_secs": one(f"select model_secs from {R} order by model_secs limit 1 offset "
                                     f"(select count(*)/2 from {R})") if one(f"select count(*) from {R}") else None,
            "updated": now()}


def cleanup_audio():
    """Delete recordings older than AUDIO_KEEP_DAYS (privacy promise on the first screen)."""
    con = db(); cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=AUDIO_KEEP_DAYS)).isoformat()
    for r in con.execute("select id, audio from readings where audio is not null and created < ?", (cut,)).fetchall():
        pathlib.Path(r["audio"]).unlink(missing_ok=True)
        with _lock, con:
            con.execute("update readings set audio=null where id=?", (r["id"],))


@app.on_event("startup")
def _startup():
    cleanup_audio()
    if getattr(app.state, "transcriber", None) is None and os.environ.get("LOAD_MODEL", "1") == "1":
        app.state.transcriber = load_transcriber()
