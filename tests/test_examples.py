"""Keep the shipped examples valid: the scripts parse, and the briefing
script matches its PDF page for page (the checks a conversion makes first)."""
import json
import os

import pytest

from podcast_generator import generator as g

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
BRIEFING = os.path.join(EXAMPLES, "briefing", "podcast-generator-intro.md")
PODCAST = os.path.join(EXAMPLES, "podcast", "neural-scaling-laws-language-statistics.md")

pytestmark = pytest.mark.skipif(not os.path.isdir(EXAMPLES), reason="examples/ not present")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_briefing_matches_its_pdf():
    pytest.importorskip("pypdfium2")
    from podcast_generator import briefing

    raw = read(BRIEFING)
    pdf = g.briefing_pdf_path(raw, BRIEFING)
    assert os.path.isfile(pdf)
    count = briefing.page_count(pdf)
    pages, warnings = g.plan_pages(g.split_pages(raw), count)
    assert [number for number, _ in pages] == list(range(1, count + 1))
    assert all(turns for _, turns in pages)  # every page is narrated
    assert warnings == []


def test_sample_output_belongs_to_the_shipped_files():
    pytest.importorskip("pypdfium2")
    from podcast_generator import briefing

    folder = os.path.join(EXAMPLES, "briefing")
    with open(os.path.join(folder, "sample-output", "podcast-generator-intro.briefing.json"),
              encoding="utf-8") as f:
        info = json.load(f)
    assert info["pdf_sha256"] == briefing.sha256(os.path.join(folder, info["pdf"]))
    # Hashed as the generator hashes it: the text as read, newlines normalized.
    import hashlib
    assert info["script_sha256"] == hashlib.sha256(read(BRIEFING).encode("utf-8")).hexdigest()


def test_podcast_has_spoken_text():
    raw = read(PODCAST)
    assert not g.has_page_markers(raw)
    turns = g.split_turns(raw, ())
    assert len(" ".join(text for _, text in turns).split()) > 900
