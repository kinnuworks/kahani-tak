"""Real speech model on synthetic clips with known planted mistakes (no mocks).
Needs the IndicConformer model files (MODEL_DIR, default ~/models/indic-conformer)."""
import json, pathlib
import pytest
from kahani import asr, scoring

FIX = pathlib.Path(__file__).parent / "fixtures"
TRUTH = json.loads((FIX / "truth.json").read_text())
CARDS = json.loads((pathlib.Path(__file__).parent.parent / "kahani" / "cards.json").read_text())["sets"][0]


@pytest.fixture(scope="module")
def model():
    return asr.Transcriber()


def test_transcribes_devanagari(model):
    text = model.transcribe_file(FIX / "paragraph-18.wav")
    assert any("ऀ" <= ch <= "ॿ" for ch in text)


def test_clean_paragraph_passes(model):
    r = scoring.score_reading("paragraph", CARDS["paragraph"], model.transcribe_file(FIX / "paragraph-18.wav"))
    assert r["passed"] and r["mistakes"] <= 1


def test_skipped_words_are_marked(model):
    # story-39 skips "एक छोटी साइकिल"
    r = scoring.score_reading("story", CARDS["story"], model.transcribe_file(FIX / "story-39.wav"))
    missed = {w["text"] for w in r["words"] if not w["ok"]}
    assert {"छोटी", "साइकिल"} <= missed


def test_phone_formats_decode(model):
    # Android Chrome records webm/opus; must decode to the same words as the wav
    a = scoring.normalize(model.transcribe_file(FIX / "paragraph-18.wav"))
    b = scoring.normalize(model.transcribe_file(FIX / "paragraph-18.webm"))
    assert len(set(a) & set(b)) >= len(set(a)) - 2   # compare distinct words; the card repeats है and गाय


def test_silence_is_nothing_heard(model, tmp_path):
    import numpy as np, soundfile as sf
    p = tmp_path / "silence.wav"; sf.write(p, np.zeros(16000 * 2, dtype="float32"), 16000)
    with pytest.raises(scoring.NothingHeard):
        scoring.score_reading("paragraph", CARDS["paragraph"], model.transcribe_file(p))


def test_first_screen_example_is_the_models_real_output(model):
    """The labelled example on the first screen must be what the model really produces on that clip."""
    import sys
    sys.path.insert(0, str(FIX.parent.parent))
    from scripts.make_example import build
    stored = json.loads((FIX.parent.parent / "kahani/static/example.json").read_text())
    assert build(model) == stored
