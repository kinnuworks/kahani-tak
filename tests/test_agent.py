"""Class-planner agent, live LLM (no mocks). Needs ANTHROPIC_API_KEY.
The agent may only read class data through its tools; levels come from code and the teacher."""
import os, pathlib
import pytest
from fastapi.testclient import TestClient

FIX = pathlib.Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
FORBIDDEN = ["कमज़ोर", "कमजोर", "weak", "slow learner", "बुद्धू", "नालायक"]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("agentdata"))
    from kahani import server
    if getattr(server.app.state, "transcriber", None) is None:
        server.app.state.transcriber = server.load_transcriber()
    with TestClient(server.app) as c:
        yield c


def child(client, code, clips, key):
    s = client.post("/api/session", json={"klass": 3, "consent": True, "child_key": key, "teacher_code": code, "set_id": "A"}).json()
    for level, clip in clips:
        with open(FIX / clip, "rb") as f:
            r = client.post("/api/read", data={"session_id": s["session_id"], "level": level}, files={"audio": (clip, f, "audio/wav")})
            assert r.status_code == 200, r.text
    return s


def test_plan_groups_children_by_level(client):
    t = client.post("/api/teacher", json={"name": "Agent test class"}).json()
    code, H = t["code"], {"X-Teacher-Key": t["key"]}
    child(client, code, [("paragraph", "paragraph-18.wav"), ("story", "story-30.wav")], "kid-story-1")       # story
    child(client, code, [("paragraph", "paragraph-18.wav"), ("story", "paragraph-18.wav")], "kid-para-1")    # paragraph
    child(client, code, [("paragraph", "story-39.wav"), ("word", "word-13.wav")], "kid-word-1")             # word (unsure)
    assert client.post(f"/api/teacher/{code}/plan", json={}).status_code == 403
    r = client.post(f"/api/teacher/{code}/plan", json={"prompt": "कल की योजना"}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    text = d["response"]
    assert len(text) > 200 and any("ऀ" <= ch <= "ॿ" for ch in text)
    called = [c["name"] for c in d["tool_calls"]]
    assert "get_class_summary" in called
    # the agent's group sizes are the database's, not invented
    assert {k: v for k, v in d["groups"].items() if v} == {"story": 1, "paragraph": 1, "word": 1}
    for g, n in d["groups"].items():
        if n:
            assert {"story": "कहानी", "paragraph": "अनुच्छेद", "word": "शब्द", "letter": "अक्षर", "beginner": "अक्षर"}[g] in text
    assert not any(w.lower() in text.lower() for w in FORBIDDEN)
    assert "kid-" not in text                       # no internal ids or names leak


def test_studio_prompt_is_the_shipped_prompt():
    """The prompt versioned in AgentFoundry's Agent Studio is the one the live app uses."""
    root = pathlib.Path(__file__).parent.parent
    assert (root / ".codenow/agent-studio/prompts/kahani-class-planner.md").read_text() == \
        (root / "kahani/prompts/class_planner.md").read_text()
