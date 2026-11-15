"""Make the first-screen example: the real speech model and scoring run on one synthetic test clip
(macOS 'Lekha' voice reading card set A's paragraph with three words skipped). Writes
kahani/static/example.json. tests/test_asr.py checks the file still matches the model's output."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kahani import asr, scoring  # noqa: E402

CLIP = "paragraph-27.wav"


def build(model=None):
    model = model or asr.Transcriber()
    card = json.loads((ROOT / "kahani/cards.json").read_text())["sets"][0]["paragraph"]
    heard = model.transcribe_file(ROOT / "tests/fixtures" / CLIP)
    r = scoring.score_reading("paragraph", card, heard)
    return {"source": f"tests/fixtures/{CLIP} (synthetic voice, not a child)", "level": "paragraph",
            "words": r["words"], "mistakes": r["mistakes"], "passed": r["passed"],
            "needs_teacher": scoring.needs_teacher("paragraph", r["mistakes"])}


if __name__ == "__main__":
    ex = build()
    (ROOT / "kahani/static/example.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1))
    print(ex["mistakes"], ex["passed"], ex["needs_teacher"], [w["text"] for w in ex["words"] if not w["ok"]])
