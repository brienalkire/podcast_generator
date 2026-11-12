import zipfile

import pytest

from podcast_generator import generator as g
from podcast_generator import notes
from pptx_fixture import LINE_BREAK, make_pptx

DECK = [
    ([["Welcome to the ", "quarterly review."], ["Second paragraph."]], False),
    ([["Hidden slide notes."]], True),
    (None, False),                                              # no notes at all
    ([["Costs fell. [click]", LINE_BREAK, "See www.example.com for more."],
      ["# Not a header"], ["*Not the end of the script*"], ["**Key:** not metadata"]], False),
]


@pytest.fixture
def deck(tmp_path):
    return str(make_pptx(tmp_path / "Q3 review.pptx", DECK))


def test_read_slides(deck):
    slides = notes.read_slides(deck)
    assert [(s.number, s.hidden) for s in slides] == [(1, False), (2, True), (3, False), (4, False)]
    assert slides[0].notes == ["Welcome to the quarterly review.", "Second paragraph."]
    assert slides[2].notes == []
    # The slide-number placeholder isn't part of the notes.
    assert slides[3].notes[0] == "Costs fell. [click] See www.example.com for more."


def test_script_skips_hidden_slides_by_default(deck):
    script, report = notes.notes_to_script(notes.read_slides(deck), "Q3 review", "Q3 review.pdf")
    assert script.startswith("# Q3 review\n\n**Briefing:** Q3 review.pdf\n\n## Page 1\n\n"
                             "Welcome to the quarterly review.\n\nSecond paragraph.\n\n## Page 2\n\n## Page 3\n\n")
    assert "Hidden slide notes" not in script
    assert report[0] == "Numbered 3 slide(s) as pages 1 to 3."
    assert any("Left out hidden slide(s) 2" in line for line in report)
    assert any("page(s) 2 have no notes" in line for line in report)
    assert any("page(s) 3 have web addresses" in line for line in report)
    assert any("Removed 1 [bracketed]" in line for line in report)


def test_include_hidden_numbers_every_slide(deck):
    script, report = notes.notes_to_script(notes.read_slides(deck), "d", "d.pdf", include_hidden=True)
    assert "## Page 2\n\nHidden slide notes." in script and "## Page 4" in script
    assert any("Include hidden slides" in line for line in report)


def test_notes_never_become_script_markdown(deck):
    script, _ = notes.notes_to_script(notes.read_slides(deck), "d", "d.pdf")
    page3 = script.split("## Page 3")[1]
    assert "Costs fell. See www.example.com for more." in page3
    assert "\nNot a header\n" in page3
    assert "\nNot the end of the script\n" in page3
    assert "\nKey: not metadata\n" in page3
    # And the whole thing parses as a briefing with every page's text spoken.
    sections = g.split_pages(script)
    assert [m.number for m, _ in sections] == [1, 2, 3]
    assert "Key: not metadata" in sections[2][1][0][1]


def test_extract_writes_next_to_deck_and_refuses_to_overwrite(deck, tmp_path):
    path, _ = notes.extract_notes(deck)
    assert path == str(tmp_path / "Q3 review.md")
    with pytest.raises(ValueError, match="already exists"):
        notes.extract_notes(deck)


@pytest.mark.parametrize("name, content, message", [
    ("old.ppt", b"x", "old-style .ppt"),
    ("bad.pptx", b"not a zip", "not a .pptx file"),
])
def test_bad_files(tmp_path, name, content, message):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(ValueError, match=message):
        notes.read_slides(str(path))


def test_doctype_is_refused(tmp_path):
    path = tmp_path / "evil.pptx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/presentation.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')
    with pytest.raises(ValueError, match="DOCTYPE"):
        notes.read_slides(str(path))


def test_all_hidden_is_an_error(tmp_path):
    deck = make_pptx(tmp_path / "d.pptx", [([["x"]], True)])
    with pytest.raises(ValueError, match="every slide is hidden"):
        notes.notes_to_script(notes.read_slides(str(deck)), "d", "d.pdf")


def test_cli_extract_notes(deck, tmp_path, capsys):
    out = tmp_path / "narration.md"
    assert g.main(["podcast-generator", "--extract-notes", deck, "--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Q3 review")
    printed = capsys.readouterr().out
    assert f"Wrote {out}" in printed and "Numbered 3 slide(s)" in printed
    assert g.main(["podcast-generator", "--extract-notes", str(tmp_path / "none.pptx")]) == 1


def test_mcp_extract_notes(deck):
    mcp_server = pytest.importorskip("podcast_generator.mcp_server")
    result = mcp_server.extract_notes(deck)
    assert result["script"].startswith("# Q3 review")
    assert "queue_podcast" in result["next_step"]
    with pytest.raises(mcp_server.ToolError, match="not found"):
        mcp_server.extract_notes(deck + "x")
