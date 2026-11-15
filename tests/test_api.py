"""API of the parent loop, teacher confirmation and impact page, with the real speech model."""
import json, pathlib, sqlite3
import pytest
from fastapi.testclient import TestClient

FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    from kahani import server
    server.app.state.transcriber = server.load_transcriber()
    with TestClient(server.app) as c:
        yield c


def start(client, teacher=None, set_id="A"):
    body = {"klass": 3, "consent": True, "child_key": "test-child", "set_id": set_id}
    if teacher:
        body["teacher_code"] = teacher
    r = client.post("/api/session", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def read(client, sid, level, clip):
    with open(FIX / clip, "rb") as f:
        r = client.post("/api/read", data={"session_id": sid, "level": level}, files={"audio": (clip, f, "audio/wav")})
    assert r.status_code == 200, r.text
    return r.json()


def test_consent_required(client):
    r = client.post("/api/session", json={"klass": 3, "consent": False, "child_key": "x"})
    assert r.status_code == 400


def test_first_card_is_paragraph_and_clean_read_moves_to_story(client):
    s = start(client)
    assert s["level"] == "paragraph" and "रानी" in s["card"]
    r = read(client, s["session_id"], "paragraph", "paragraph-18.wav")
    assert r["passed"] is True and r["next_level"] == "story" and "सोनू" in r["next_card"]
    assert len(r["words"]) == len(s["card"].replace("।", " ").split()) and all("ok" in w for w in r["words"])
    assert r["practice"]                                     # tonight's practice is always given


def test_wrong_level_is_rejected(client):
    s = start(client)
    with open(FIX / "story-30.wav", "rb") as f:
        r = client.post("/api/read", data={"session_id": s["session_id"], "level": "story"}, files={"audio": ("a.wav", f, "audio/wav")})
    assert r.status_code == 409                              # ASER path: must read the paragraph first


def test_silence_returns_retry_not_a_result(client, tmp_path):
    import numpy as np, soundfile as sf
    p = tmp_path / "quiet.wav"; sf.write(p, np.zeros(16000 * 2, dtype="float32"), 16000)
    s = start(client)
    with open(p, "rb") as f:
        r = client.post("/api/read", data={"session_id": s["session_id"], "level": "paragraph"}, files={"audio": ("q.wav", f, "audio/wav")})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "nothing_heard"


def test_teacher_queue_confirm_and_impact(client):
    t = client.post("/api/teacher", json={"name": "Class 3B"}).json()
    code = t["code"]
    s = start(client, teacher=code)
    r = read(client, s["session_id"], "paragraph", "paragraph-18.wav")       # clean: not unsure
    r2 = read(client, s["session_id"], "story", "story-39.wav")              # skipped words
    q = client.get(f"/api/teacher/{code}/queue").json()["items"]
    ids = [i["reading_id"] for i in q]
    assert r2["reading_id"] in ids or not r2["needs_teacher"]
    assert all(i["level"] in ("paragraph", "story", "word", "letter") for i in q)
    # audio only with the teacher's code
    assert client.get(f"/api/teacher/WRONG/audio/{r['reading_id']}").status_code == 404
    # teacher marks every word right on the story -> passes, final level updates for the parent
    item = next(i for i in client.get(f"/api/teacher/{code}/all").json()["items"] if i["reading_id"] == r2["reading_id"])
    c = client.post(f"/api/teacher/{code}/confirm", json={"reading_id": r2["reading_id"], "wrong": []}).json()
    assert c["passed"] is True and c["mistakes"] == 0
    st = client.get(f"/api/session/{s['session_id']}").json()
    assert st["final_level"] == "story" and st["teacher_checked"] is True
    # audio deleted once the teacher has checked it
    assert client.get(f"/api/teacher/{code}/audio/{r2['reading_id']}").status_code == 410
    imp = client.get("/api/impact").json()
    db = sqlite3.connect(pathlib.Path(__import__("os").environ["DATA_DIR"]) / "kahani.db")
    assert imp["children_checked"] == db.execute("select count(distinct child_key) from sessions where id in (select session_id from readings)").fetchone()[0]
    assert imp["readings"] == db.execute("select count(*) from readings").fetchone()[0]
    assert imp["teacher_checked"] == db.execute("select count(*) from readings where confirmed_at is not null").fetchone()[0]
    assert set(imp["levels"]) == {"beginner", "letter", "word", "paragraph", "story"}


def test_impact_page_and_parent_page_serve(client):
    for path in ["/", "/impact", "/teacher"]:
        r = client.get(path)
        assert r.status_code == 200 and "Kahani Tak" in r.text


def test_test_traffic_is_not_counted_as_impact(client, monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "t0ken")
    before = client.get("/api/impact").json()["children_checked"]
    body = {"klass": 3, "consent": True, "child_key": "probe-child-x", "set_id": "A"}
    s = client.post("/api/session", json=body, headers={"X-Test-Token": "t0ken"}).json()
    with open(FIX / "paragraph-18.wav", "rb") as f:
        client.post("/api/read", data={"session_id": s["session_id"], "level": "paragraph"}, files={"audio": ("a.wav", f, "audio/wav")})
    assert client.get("/api/impact").json()["children_checked"] == before
    # a wrong token is an ordinary (counted) session, never an error
    s2 = client.post("/api/session", json={**body, "child_key": "probe-child-y"}, headers={"X-Test-Token": "nope"}).json()
    with open(FIX / "paragraph-18.wav", "rb") as f:
        client.post("/api/read", data={"session_id": s2["session_id"], "level": "paragraph"}, files={"audio": ("a.wav", f, "audio/wav")})
    assert client.get("/api/impact").json()["children_checked"] == before + 1
