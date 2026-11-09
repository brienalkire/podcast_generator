import numpy as np
import pytest

from podcast_generator import generator as g

DIALOGUE = """\
# Episode
**Speakers:** Maya (host) and Theo
**Voices:** Maya=af_heart, Theo=bm_george

---

**INTRO**

Maya: Welcome to the *show*.

**Theo:** Thanks, Maya.

And a second paragraph from Theo.

maya: Lowercase labels work too.

---

*Source: a citation that ends the script.*

Maya: never spoken.
"""


def test_voices_line_parsed():
    assert g.parse_voices_metadata(DIALOGUE) == {"Maya": "af_heart", "Theo": "bm_george"}


def test_no_voices_line_is_single_narrator():
    assert g.resolve_speaker_voices("Maya: hi") == {}


def test_missing_voices_filled_with_distinct_defaults():
    voices = g.resolve_speaker_voices("**Voices:** A, B=af_heart, C\n\nA: hi")
    assert voices == {"A": "bm_george", "B": "af_heart", "C": "am_michael"}


@pytest.mark.parametrize("line, message", [
    ("**Voices:** Maya=zz_nobody", "unknown voice"),
    ("**Voices:** Maya, maya", "twice"),
    ("**Voices:** =af_heart", "unusable speaker name"),
    ("**Voices:**", "names no speakers"),
])
def test_bad_voices_line(line, message):
    with pytest.raises(ValueError, match=message):
        g.resolve_speaker_voices(line + "\n\nMaya: hi")


def test_split_turns():
    turns = g.split_turns(DIALOGUE, g.resolve_speaker_voices(DIALOGUE))
    assert turns == [
        ("Maya", "Welcome to the show."),
        ("Theo", "Thanks, Maya.\n\nAnd a second paragraph from Theo."),
        ("Maya", "Lowercase labels work too."),
    ]


def test_text_before_first_label_is_narration():
    script = "**Voices:** Maya\n\nAn introduction.\n\nMaya: Hello."
    assert g.split_turns(script, {"Maya": "af_heart"}) == [
        (None, "An introduction."), ("Maya", "Hello.")]


def test_unknown_label_is_ordinary_text():
    script = "**Voices:** Maya\n\nMaya: Note: this stays."
    assert g.split_turns(script, {"Maya": "af_heart"}) == [("Maya", "Note: this stays.")]


def test_bold_section_label_not_spoken_in_single_narrator_scripts():
    assert g.strip_markdown("**PART ONE**\n\nHello **there**.") == "Hello there."


def test_spoken_text_counts_dialogue_words():
    assert g.spoken_text(DIALOGUE).split()[:3] == ["Welcome", "to", "the"]


class FakeEngine:
    sample_rate = 100

    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice, speed=1.0, lang_code=None):
        self.calls.append((text, voice, lang_code))
        return np.ones(10, dtype=np.float32)


def test_process_job_voices_each_turn_with_pauses(tmp_path, monkeypatch):
    script = tmp_path / "talk.md"
    script.write_text(DIALOGUE, encoding="utf-8")
    written = {}
    monkeypatch.setattr(g, "write_audio",
                        lambda audio, path, fmt, rate: written.update(audio=audio))
    engine = FakeEngine()
    args = g.parse_args(["podcast-generator", "--voice", "am_echo"])
    g.process_job(engine, str(script), str(tmp_path / "talk.mp3"), args)

    assert [(voice, lang) for _, voice, lang in engine.calls] == [
        ("af_heart", "a"), ("bm_george", "b"), ("af_heart", "a")]
    pause = int(engine.sample_rate * g.TURN_PAUSE_SECONDS)
    assert len(written["audio"]) == 3 * 10 + 2 * pause


def test_process_job_single_narrator_unchanged(tmp_path, monkeypatch):
    script = tmp_path / "solo.md"
    script.write_text("**Voice:** bm_george\n\nMaya: just prose here.", encoding="utf-8")
    monkeypatch.setattr(g, "write_audio", lambda *a: None)
    engine = FakeEngine()
    g.process_job(engine, str(script), str(tmp_path / "solo.mp3"),
                  g.parse_args(["podcast-generator"]))
    assert engine.calls == [("Maya: just prose here.", "bm_george", "b")]
