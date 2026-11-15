"""Run AgentFoundry's Agent Studio eval suite for the class planner from the command line.

Scoring is a line-for-line port of AgentFoundry's scoreCase (src/studio.js, v0.1.80): the first
assertion key present decides the case. The same suite runs in AgentFoundry's Agents -> Eval tab.
Usage: python scripts/af_eval.py [suite.json]   (needs ANTHROPIC_API_KEY)
"""
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kahani.agent import MODEL  # noqa: E402


def score_case(text, c):
    t = str(text or "")
    if c.get("expected_equals") is not None:
        ok = t.strip() == str(c["expected_equals"]).strip()
        return ok, "exact match" if ok else "expected exact match"
    if c.get("expected_regex"):
        ok = re.search(c["expected_regex"], t, re.I) is not None
        return ok, "regex matched" if ok else "regex did not match"
    if c.get("expected_contains"):
        ok = str(c["expected_contains"]).lower() in t.lower()
        return ok, "contains match" if ok else f'missing "{c["expected_contains"]}"'
    if isinstance(c.get("expected_all_contains"), list):
        missing = [s for s in c["expected_all_contains"] if str(s).lower() not in t.lower()]
        return not missing, "all contains matched" if not missing else "missing: " + ", ".join(missing)
    if isinstance(c.get("expected_any_contains"), list):
        found = next((s for s in c["expected_any_contains"] if str(s).lower() in t.lower()), None)
        return found is not None, f'matched "{found}"' if found else "none of expected_any_contains matched"
    if isinstance(c.get("must_not_contain"), list):
        bad = next((s for s in c["must_not_contain"] if str(s).lower() in t.lower()), None)
        return bad is None, f'forbidden term "{bad}" present' if bad else "no forbidden terms"
    return True, "no assertion (smoke test)"


def main():
    import anthropic
    path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".codenow/agent-studio/evals/kahani-class-planner.json"
    suite = json.loads(path.read_text())
    client = anthropic.Anthropic()
    passed = 0
    rows = []
    for c in suite["cases"]:
        msg = client.messages.create(model=MODEL, max_tokens=2000, system=c.get("system") or suite.get("system"),
                                     messages=[{"role": "user", "content": c["input"]}])
        text = "".join(b.text for b in msg.content if b.type == "text")
        ok, why = score_case(text, c)
        passed += ok
        rows.append({"name": c["name"], "pass": ok, "reason": why})
        print(("PASS " if ok else "FAIL ") + c["name"] + " - " + why, flush=True)
    out = ROOT / ".codenow/agent-studio/evals/results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "kahani-class-planner-cli-latest.json").write_text(json.dumps({"model": MODEL, "passed": passed, "total": len(rows), "cases": rows}, ensure_ascii=False, indent=2))
    print(f"{passed}/{len(rows)} passed ({MODEL})")
    sys.exit(0 if passed == len(rows) else 1)


if __name__ == "__main__":
    main()
