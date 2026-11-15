"""Scoring rules. Written before kahani/scoring.py; sources: ASER 2024 assessment tasks
(letters/words: at least 4 of 5; paragraph/story: whole text with 3 or fewer mistakes) and our
real-child test (spelling equivalences, letter consonant rule) recorded in STATE.md."""
import json, pathlib
import pytest
from kahani import scoring as s

CARDS = json.loads((pathlib.Path(__file__).parent.parent / "kahani" / "cards.json").read_text())
PARA = CARDS["sets"][0]["paragraph"]          # मेरा नाम रानी है। ...


def test_clean_reading_has_no_mistakes():
    r = s.score_reading("paragraph", PARA, "मेरा नाम रानी है मेरे घर में एक गाय है गाय का रंग सफेद है वह घास खाती है")
    assert r["mistakes"] == 0 and r["passed"] is True
    assert all(w["ok"] for w in r["words"])
    assert [w["text"] for w in r["words"]][:3] == ["मेरा", "नाम", "रानी"]   # card words, in card order


def test_wrong_and_skipped_words_count_and_are_marked():
    heard = "मेरा नम रानी है मेरे घर में एक गई है गाय का रंग सफेद है वह खाती है"   # नम, गई wrong; घास skipped
    r = s.score_reading("paragraph", PARA, heard)
    assert r["mistakes"] == 3 and r["passed"] is True                 # 3 or fewer = pass (ASER)
    bad = [w["text"] for w in r["words"] if not w["ok"]]
    assert bad == ["नाम", "गाय", "घास"]


def test_four_mistakes_fail_paragraph():
    heard = "मेरा नम रानी है मेरे घर में एक गई है गई का रंग सफेद है वह खाती है"
    assert s.score_reading("paragraph", PARA, heard)["passed"] is False


def test_extra_words_said_are_not_mistakes():
    heard = "मेरा मेरा नाम रानी है मेरे घर में एक गाय है गाय का रंग सफेद है वह घास खाती है"
    assert s.score_reading("paragraph", PARA, heard)["mistakes"] == 0


def test_spelling_variants_hindi_treats_as_same_word():
    # chandrabindu/anusvara, nukta, ये/ए are the same word read aloud
    assert s.normalize("वहाँ हँसते गये चाहिये सफ़ेद") == s.normalize("वहां हंसते गए चाहिए सफेद")


def test_real_misreadings_still_differ():
    for a, b in [("नल", "नाल"), ("घर", "गर"), ("कमल", "कमला"), ("छाता", "छत्ता")]:
        assert s.normalize(a) != s.normalize(b)


def test_word_level_four_of_five():
    words = CARDS["sets"][0]["word"]            # घर नल बस कमल पानी
    assert s.score_reading("word", words, "घर नल बस कमल पनी")["passed"] is True
    assert s.score_reading("word", words, "घर नाल बस कमला पनी")["passed"] is False


def test_letter_counts_when_consonant_matches():
    letters = CARDS["sets"][0]["letter"]        # क म स ल प
    r = s.score_reading("letter", letters, "का मा सा ला पा")   # children voice क as "का"
    assert r["mistakes"] == 0 and r["passed"] is True
    r = s.score_reading("letter", letters, "का ना सा रा पा")
    assert r["mistakes"] == 2 and r["passed"] is False


def test_empty_transcript_is_an_error_not_a_result():
    with pytest.raises(s.NothingHeard):
        s.score_reading("paragraph", PARA, "   ")


@pytest.mark.parametrize("level,passed,expected", [
    ("paragraph", True, ("story", None)),
    ("paragraph", False, ("word", None)),
    ("story", True, (None, "story")),
    ("story", False, (None, "paragraph")),
    ("word", True, (None, "word")),
    ("word", False, ("letter", None)),
    ("letter", True, (None, "letter")),
    ("letter", False, (None, "beginner")),
])
def test_aser_path(level, passed, expected):
    # ASER starts at the paragraph; steps up to the story or down to words, then letters
    assert s.next_step(level, passed) == expected


@pytest.mark.parametrize("level,mistakes,unsure", [
    ("paragraph", 0, False), ("paragraph", 1, False), ("paragraph", 2, True), ("paragraph", 3, True),
    ("paragraph", 4, True), ("paragraph", 5, False), ("story", 3, True), ("story", 9, False),
    ("word", 0, True), ("letter", 5, True),
])
def test_teacher_check_when_unsure(level, mistakes, unsure):
    # within 1 of the pass line (3) for paragraph/story, and every word/letter result
    assert s.needs_teacher(level, mistakes) is unsure


def test_cards_follow_aser_format():
    for st in CARDS["sets"]:
        assert len(st["letter"]) == 5 and len(st["word"]) == 5
        para = [x for x in st["paragraph"].split("।") if x.strip()]
        story = [x for x in st["story"].split("।") if x.strip()]
        assert len(para) == 4 and max(len(x.split()) for x in para) <= 6
        assert 7 <= len(story) <= 10
