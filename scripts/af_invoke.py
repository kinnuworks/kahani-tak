"""Call the live class-planner agent exactly the way AgentFoundry's HTTP invoker does
(manifest invocationUrl, promptField/responseField, header auth, AF payload shape) and check the answer."""
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
m = json.loads((ROOT / ".codenow/agent-studio/agents/kahani-class-planner.json").read_text())
payload = {m["promptField"]: "कल की योजना", "system": "",
           "agent": {"id": m["slug"], "name": m["name"], "function": m["function"]},
           "guardrails": {}, "metadata": {"invokedBy": "codenow-executive"}}
req = urllib.request.Request(m["invocationUrl"], data=json.dumps(payload).encode(), method=m["method"], headers={
    "Content-Type": "application/json", "User-Agent": "AgentFoundry/0.1 (executive-agent-test)",
    m["auth"]["headerName"]: m["auth"]["headerValue"]})
d = json.load(urllib.request.urlopen(req, timeout=240))
text = d[m["responseField"]]
groups = {k: v for k, v in d["groups"].items() if v}
ok = bool(groups) and "get_class_summary" in [c["name"] for c in d["tool_calls"]] and "**" not in text \
    and all({"story": "कहानी", "paragraph": "अनुच्छेद", "word": "शब्द", "letter": "अक्षर"}.get(g, "") in text for g in groups)
print(("AF invocation OK: " if ok else "AF invocation FAILED: ") + json.dumps(groups))
sys.exit(0 if ok else 1)
