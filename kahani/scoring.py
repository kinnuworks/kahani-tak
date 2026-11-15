"""Count a child's reading mistakes against a card, the ASER way.

No language model is involved here. The speech model writes down what it heard; this code lines that
up with the card and counts mistakes. Rules (ASER 2024 assessment tasks): letters and words pass at
4 of 5 correct; a paragraph or story passes with 3 or fewer mistakes.
"""
import difflib
import re
import unicodedata

PASS_MAX_MISTAKES = 3            # paragraph / story
ITEMS_TO_PASS = 4                # of 5 letters or words
ORDER_DOWN = {"paragraph": "word", "word": "letter"}


class NothingHeard(ValueError):
    """The speech model returned no words: never score that as a reading."""


_PUNCT = re.compile(r"[।॥,.!?\"'“”‘’\-–—:;()]")


def normalize(text):
    """Card or transcript -> comparable words. Only spellings Hindi treats as the same word are merged:
    chandrabindu = anusvara, nukta dropped, ये = ए and यी = ई inside a word (गये/गए, चाहिये/चाहिए)."""
    t = unicodedata.normalize("NFC", text).replace("़", "").replace("ँ", "ं")
    t = re.sub(r"(?<=[ऀ-ुृ-ौक-ह])ये", "ए", t)
    t = re.sub(r"(?<=[ऀ-ुृ-ौक-ह])यी", "ई", t)
    return _PUNCT.sub(" ", t).split()


def _consonant(token):
    m = re.search(r"[क-ह]", unicodedata.normalize("NFC", token).replace("़", ""))
    return m.group(0) if m else token


def score_reading(level, card, heard):
    """card: text (paragraph/story) or list of 5 items (word/letter). Returns per-card-word marks."""
    shown = card if isinstance(card, list) else _PUNCT.sub(" ", card).split()
    want = [normalize(w)[0] if normalize(w) else w for w in shown]
    got = normalize(heard)
    if not got:
        raise NothingHeard("no words heard")
    if level == "letter":                       # children say क as "का": compare the consonant
        want, got = [_consonant(w) for w in want], [_consonant(w) for w in got]
    ok = [False] * len(want)
    for op, i1, i2, _, _ in difflib.SequenceMatcher(None, want, got, autojunk=False).get_opcodes():
        if op == "equal":
            for i in range(i1, i2):
                ok[i] = True
    mistakes = ok.count(False)
    passed = (len(want) - mistakes) >= ITEMS_TO_PASS if level in ("letter", "word") else mistakes <= PASS_MAX_MISTAKES
    return {"level": level, "words": [{"text": w, "ok": k} for w, k in zip(shown, ok)],
            "mistakes": mistakes, "total": len(want), "passed": passed}


def next_step(level, passed):
    """ASER path. Returns (next level to test, final level) - exactly one is set."""
    if level == "paragraph":
        return ("story", None) if passed else ("word", None)
    if level == "story":
        return (None, "story") if passed else (None, "paragraph")
    if level == "word":
        return (None, "word") if passed else ("letter", None)
    if level == "letter":
        return (None, "letter") if passed else (None, "beginner")
    raise ValueError(level)


def needs_teacher(level, mistakes):
    """Unsure results go to the teacher: any letter/word result (our real-child test: near coin-flip),
    and paragraph/story results within 1 mistake of the pass line."""
    if level in ("letter", "word"):
        return True
    return abs(mistakes - PASS_MAX_MISTAKES) <= 1
