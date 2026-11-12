"""The connector's briefing tools: inspect, validate, queue, status."""
import asyncio
import json

import pytest

mcp_server = pytest.importorskip("podcast_generator.mcp_server")
pytest.importorskip("pypdfium2")

from pdf_fixture import make_pdf  # noqa: E402

m = mcp_server
SIZE = (720, 405)
SCRIPT = "# Deck\n\n## Page 1\n\nHello there.\n\n## Page 2\n\nAnd goodbye."


@pytest.fixture
def server(folders, monkeypatch, tmp_path):
    monkeypatch.setattr(m, "_watch_state", lambda: "off")
    monkeypatch.setattr(m, "_converting", lambda: False)
    from podcast_generator import briefing
    monkeypatch.setattr(briefing, "check_ffmpeg", lambda: None)
    pdf = make_pdf(tmp_path / "Q3 deck.pdf", [("Agenda", SIZE), ("", SIZE)])
    return folders, str(pdf)


def test_inspect_reports_pages_and_scanned_ones(server):
    _, pdf = server
    result = m.inspect_briefing(pdf)
    assert result["pages"] == 2
    assert result["page_text"][0] == {"page": 1, "title": "Agenda", "text": "Agenda"}
    assert result["page_text"][1]["no_text_layer"] is True
    assert "pages 2 have no text layer" in result["warning"]
    assert result["script_skeleton"].startswith("## Page 1\n\n")


def test_inspect_needs_a_real_pdf_path(server, tmp_path):
    with pytest.raises(m.ToolError, match="PDF not found"):
        m.inspect_briefing(str(tmp_path / "missing.pdf"))
    with pytest.raises(m.ToolError, match="not a .pdf"):
        m.inspect_briefing(str(tmp_path / "notes.docx"))


def test_validate_reports_errors_without_raising(server):
    _, pdf = server
    bad = m.validate_briefing("## Page 1\n\nA.\n\n## Page 5\n\nB.", pdf)
    assert bad["ok"] is False and "the PDF has pages 1 to 2" in bad["errors"]
    good = m.validate_briefing("## Page 2\n\nOnly page two.", pdf)
    assert good["ok"] is True and good["pages_shown"] == [1, 2]
    assert any("page 1 has no section" in w for w in good["warnings"])


def test_queue_briefing_copies_pdf_and_sets_line(server):
    (inputs, _, _), pdf = server
    result = m.queue_podcast("deck", SCRIPT, pdf=pdf)
    queue = inputs.parent / "connector_queue"
    assert (queue / "deck.pdf").read_bytes() == open(pdf, "rb").read()
    saved = (queue / "deck.md").read_text(encoding="utf-8")
    assert "**Briefing:** deck.pdf" in saved
    assert result["briefing"] == {"pdf": pdf, "pdf_pages": 2, "pages_shown": [1, 2]}
    assert result["spoken_words"] == 4


def test_queue_refuses_a_mismatched_briefing_and_queues_nothing(server):
    (inputs, _, _), pdf = server
    with pytest.raises(m.ToolError, match="no '## Page N' markers"):
        m.queue_podcast("deck", "Just prose, no pages.", pdf=pdf)
    assert not (inputs.parent / "connector_queue").exists()


def test_queue_reads_an_absolute_briefing_line(server):
    (inputs, _, _), pdf = server
    result = m.queue_podcast("deck", f"**Briefing:** {pdf}\n\n" + SCRIPT)
    assert result["briefing"]["pdf_pages"] == 2
    saved = (inputs.parent / "connector_queue" / "deck.md").read_text(encoding="utf-8")
    assert "**Briefing:** deck.pdf" in saved and pdf not in saved


def test_requeue_as_plain_podcast_drops_old_pdf(server):
    (inputs, _, _), pdf = server
    m.queue_podcast("deck", SCRIPT, pdf=pdf)
    m.queue_podcast("deck", "Just a podcast now.", replace=True)
    assert not (inputs.parent / "connector_queue" / "deck.pdf").exists()


def test_status_and_list_report_videos(server):
    (_, outputs, _), _ = server
    outputs.mkdir()
    (outputs / "deck.mp4").write_bytes(b"x")
    (outputs / "deck.srt").write_text("1\n", encoding="utf-8")
    (outputs / "deck.briefing.json").write_text(json.dumps({"total_seconds": 90}), encoding="utf-8")
    status = asyncio.run(m.podcast_status("deck"))
    assert status["status"] == "done" and status["kind"] == "video"
    assert status["duration_minutes"] == 1.5 and status["subtitles"].endswith("deck.srt")
    listing = m.list_podcasts()
    assert [v["name"] for v in listing["recent_briefings"]] == ["deck.mp4"]
    assert listing["recent_audio"] == []
    with pytest.raises(m.ToolError, match="already exists"):
        m.queue_podcast("deck", "Again.")
