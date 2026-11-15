"""Class-planner agent: groups a teacher's children by the reading level they reached and writes
tomorrow's plan. The LLM reads class data only through these tools; levels come from code/teacher."""
import collections
import json
import os
import pathlib

PROMPT = (pathlib.Path(__file__).parent / "prompts" / "class_planner.md").read_text(encoding="utf-8")
MODEL = os.environ.get("PLANNER_MODEL", "claude-sonnet-5-5")
LEVEL_HI = {"beginner": "अक्षर से पहले", "letter": "अक्षर", "word": "शब्द", "paragraph": "अनुच्छेद", "story": "कहानी"}
NEXT = {"beginner": "letter", "letter": "word", "word": "paragraph", "paragraph": "story", "story": "story"}

TOOLS = [
    {"name": "get_class_summary",
     "description": "Children in this class with the reading level each reached (latest finished check), group sizes by level, and how many readings still wait for the teacher's check.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_missed_words",
     "description": "The card words most often missed by children in one level group.",
     "input_schema": {"type": "object", "properties": {"level": {"type": "string", "enum": list(LEVEL_HI)}}, "required": ["level"]}},
    {"name": "get_practice_material",
     "description": "Practice material one step above a level group (letters, words, sentences or a story) from the app's own cards.",
     "input_schema": {"type": "object", "properties": {"level": {"type": "string", "enum": list(LEVEL_HI)}}, "required": ["level"]}},
]


class ClassData:
    """Read-only view of one teacher's class, built by the server."""

    def __init__(self, children, waiting, missed, cards):
        self.children = children      # [{"label": "बच्चा 1", "level": "word", "teacher_checked": bool}]
        self.waiting = waiting
        self.missed = missed          # level -> Counter(word -> count)
        self.cards = cards

    def groups(self):
        g = collections.Counter(c["level"] for c in self.children)
        return {k: g.get(k, 0) for k in LEVEL_HI}

    def run(self, name, args):
        if name == "get_class_summary":
            return {"children": [{**c, "level": LEVEL_HI[c["level"]]} for c in self.children],
                    "groups": {LEVEL_HI[k]: v for k, v in self.groups().items() if v},
                    "readings_waiting_for_teacher": self.waiting}
        level = args.get("level")
        if level not in LEVEL_HI:
            return {"error": "unknown level"}
        if name == "get_missed_words":
            return {"level": LEVEL_HI[level],
                    "most_missed": [w for w, _ in self.missed.get(level, collections.Counter()).most_common(6)]}
        if name == "get_practice_material":
            nxt = NEXT[level]
            return {"for_group": LEVEL_HI[level], "practise_at": LEVEL_HI[nxt], "material": self.cards[nxt]}
        return {"error": "unknown tool"}


class PlannerUnavailable(RuntimeError):
    pass


def plan(data, teacher_note="", max_turns=8):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise PlannerUnavailable("ANTHROPIC_API_KEY is not set")
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    ask = "कल की पढ़ाई की योजना बनाइए।" + (f" टीचर का नोट: {teacher_note[:500]}" if teacher_note else "")
    messages = [{"role": "user", "content": ask}]
    calls = []
    for _ in range(max_turns):
        msg = client.messages.create(model=MODEL, max_tokens=2500, system=PROMPT, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": msg.content})
        uses = [b for b in msg.content if b.type == "tool_use"]
        if not uses:
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            return {"response": text, "tool_calls": calls, "groups": data.groups(), "model": MODEL}
        results = []
        for u in uses:
            out = data.run(u.name, u.input or {})
            calls.append({"name": u.name, "input": u.input})
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(out, ensure_ascii=False)})
        messages.append({"role": "user", "content": results})
    raise PlannerUnavailable("planner did not finish within the turn limit")
