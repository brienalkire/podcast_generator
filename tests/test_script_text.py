import pytest

from podcast_generator import generator as g

SCRIPT = """\
# Episode One
**Author:** Someone
**Voice:** bm_george

*Source: a note before the prose*

---

## OPENING

Welcome to **the show**. Here is *some* `code` and a [link](https://example.com).

## CLOSING

That's all.

*End of script.*

Appendix text that should never be spoken.
"""


def test_strip_markdown_keeps_only_spoken_prose():
    text = g.strip_markdown(SCRIPT)
    assert text == (
        "Welcome to the show. Here is some code and a link.\n\nThat's all."
    )


def test_italic_line_before_prose_is_skipped_not_the_end():
    assert g.strip_markdown("*Source: x*\n\nHello there.") == "Hello there."


def test_voice_from_script_metadata():
    assert g.resolve_voice(SCRIPT, None) == "bm_george"


def test_cli_voice_overrides_script():
    assert g.resolve_voice(SCRIPT, "af_bella") == "af_bella"


def test_default_voice_when_none_given():
    assert g.resolve_voice("Just prose.", None) == g.DEFAULT_VOICE


def test_unknown_script_voice_is_an_error():
    with pytest.raises(ValueError, match="unknown voice"):
        g.resolve_voice("**Voice:** zz_nobody\n\nHi.", None)
