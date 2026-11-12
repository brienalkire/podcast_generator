import pytest

from podcast_generator import generator as g
from test_dialogue import FakeEngine

BRIEFING = """\
# Quarterly Review
**Voices:** Maya=af_heart, Theo=bm_george

## Page 1

Maya: Welcome to the *review*.

## Page 2

Theo: Revenue is up.

Still Theo, on the next paragraph.

## Page 3

Carried over: still Theo, since nobody else spoke.

### Page 5 (skip)

## Page 6

*End of script.*

## Page 7

Never spoken.
"""


def numbers(sections):
    return [(m.number, m.skip) for m, _ in sections]


def test_split_pages_keeps_speakers_across_markers():
    sections = g.split_pages(BRIEFING, g.resolve_speaker_voices(BRIEFING))
    assert numbers(sections) == [(1, False), (2, False), (3, False), (5, True), (6, False)]
    assert sections[0][1] == [("Maya", "Welcome to the review.")]
    assert sections[1][1] == [("Theo", "Revenue is up.\n\nStill Theo, on the next paragraph.")]
    assert sections[2][1] == [("Theo", "Carried over: still Theo, since nobody else spoke.")]


def test_end_of_script_line_ends_the_whole_briefing():
    sections = g.split_pages(BRIEFING, g.resolve_speaker_voices(BRIEFING))
    assert 7 not in [m.number for m, _ in sections]
    assert sections[-1][1] == []


def test_markers_are_still_dropped_from_ordinary_scripts():
    assert g.strip_markdown("## Page 1\n\nHello.\n\n## Slide 2\n\nBye.") == "Hello.\n\nBye."


def test_text_before_first_marker_is_an_error():
    with pytest.raises(ValueError, match="before the first"):
        g.split_pages("# Title\n**Voice:** af_heart\n\nIntro.\n\n## Page 1\n\nHi.")


def test_title_and_metadata_before_first_marker_are_fine():
    sections = g.split_pages("# Title\n**Voice:** af_heart\n\n## Page 1\n\nHi.")
    assert sections[0][1] == [(None, "Hi.")]


@pytest.mark.parametrize("header", ["## Slide 2", "## Page two", "## Page 2: Results"])
def test_mistyped_marker_is_an_error(header):
    with pytest.raises(ValueError, match="isn't a page marker"):
        g.split_pages(f"## Page 1\n\nHi.\n\n{header}\n\nMore.")


def test_plan_fills_gaps_and_drops_skipped_pages():
    sections = g.split_pages(BRIEFING, g.resolve_speaker_voices(BRIEFING))
    pages, warnings = g.plan_pages(sections, page_count=7)
    assert [n for n, _ in pages] == [1, 2, 3, 4, 6, 7]
    assert [n for n, turns in pages if not turns] == [4, 6, 7]
    assert any("page 4 has no section" in w for w in warnings)
    assert any("page 6's section is empty" in w for w in warnings)


def test_plan_without_page_count_runs_to_last_marker():
    pages, _ = g.plan_pages(g.split_pages("## Page 2\n\nHi."))
    assert [n for n, _ in pages] == [1, 2]


def test_skip_with_text_warns():
    _, warnings = g.plan_pages(g.split_pages("## Page 1\n\nHi.\n\n## Page 2 (skip)\n\nGone."))
    assert any("marked (skip)" in w for w in warnings)


def test_long_section_warns(monkeypatch):
    monkeypatch.setattr(g, "LONG_SECTION_WORDS", 3)
    _, warnings = g.plan_pages(g.split_pages("## Page 1\n\none two three four"))
    assert any("4 words" in w for w in warnings)


@pytest.mark.parametrize("script, page_count, message", [
    ("Just prose.", 4, "no '## Page N' markers found. The PDF has 4 pages"),
    ("## Page 5\n\nHi.", 4, "the PDF has pages 1 to 4"),
    ("## Page 0\n\nHi.", None, "pages start at 1"),
    ("## Page 1\n\nA.\n\n## Page 1\n\nB.", None, "page 1 has two sections"),
    ("## Page 2\n\nA.\n\n## Page 1\n\nB.", None, "page 1 comes after page 2"),
    ("## Page 1 (skip)", None, "every page is marked"),
])
def test_plan_errors(script, page_count, message):
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        g.plan_pages(g.split_pages(script), page_count)


def test_plan_reports_every_error_at_once():
    script = "## Page 3\n\nA.\n\n## Page 2\n\nB.\n\n## Page 9\n\nC."
    with pytest.raises(ValueError) as caught:
        g.plan_pages(g.split_pages(script), page_count=4)
    assert "page 2 comes after page 3" in str(caught.value)
    assert "'## Page 9'" in str(caught.value)


def test_synthesize_pages_times_each_page():
    pages = [(1, [(None, "Hello.")]), (2, [])]
    engine = FakeEngine()
    voices = g.ScriptVoices("", "x.md", g.parse_args(["podcast-generator"]))
    (p1, audio1, hold1), (p2, audio2, hold2) = g.synthesize_pages(engine, pages, voices)
    assert hold1 == pytest.approx(10 / engine.sample_rate + g.INTER_PAGE_PAUSE_SECONDS)
    assert audio2 is None and hold2 == g.SILENT_HOLD_SECONDS


def test_preview_prints_table_and_saves_nothing(tmp_path, monkeypatch, capsys):
    script = tmp_path / "brief.md"
    script.write_text("## Page 1\n\nHello there.\n\n## Page 3\n\nBye.", encoding="utf-8")
    monkeypatch.setattr(g, "write_audio", lambda *a: pytest.fail("preview wrote audio"))
    g.preview_job(FakeEngine(), str(script), g.parse_args(["podcast-generator", "--preview"]))
    out = capsys.readouterr().out
    assert "page 2 has no section" in out
    assert "silent" in out and "Total: 3 page(s)" in out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["brief.md"]


def test_preview_needs_a_script(capsys):
    assert g.run(g.parse_args(["podcast-generator", "--preview"])) == 1
    assert "--preview needs a script" in capsys.readouterr().err
