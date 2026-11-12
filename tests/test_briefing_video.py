import json
import shutil
import subprocess

import numpy as np
import pytest

from podcast_generator import generator as g
from pdf_fixture import make_pdf
from test_dialogue import FakeEngine

pytest.importorskip("pypdfium2")
from podcast_generator import briefing  # noqa: E402

LANDSCAPE = (720, 405)  # 16:9
PORTRAIT = (612, 792)   # US Letter

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


class SpeechEngine(FakeEngine):
    """A fake engine at a realistic rate: 0.5 s of quiet tone per call."""
    sample_rate = 24000

    def synthesize(self, text, voice, speed=1.0, lang_code=None):
        self.calls.append((text, voice, lang_code))
        return np.full(12000, 0.1, dtype=np.float32)


def test_page_count_and_texts(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf", [("Hello page one", LANDSCAPE), ("", PORTRAIT)])
    assert briefing.page_count(str(pdf)) == 2
    assert briefing.page_texts(str(pdf)) == ["Hello page one", ""]


def test_missing_and_broken_pdfs(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        briefing.page_count(str(tmp_path / "none.pdf"))
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pytest.raises(ValueError, match="can't read the briefing PDF"):
        briefing.page_count(str(bad))


def test_render_letterboxes_onto_canvas(tmp_path):
    pdf = make_pdf(tmp_path / "d.pdf", [("Wide", LANDSCAPE), ("Tall", PORTRAIT)])
    doc = briefing.open_pdf(str(pdf))
    try:
        wide, tall = briefing.render_page(doc, 1), briefing.render_page(doc, 2)
    finally:
        doc.close()
    assert wide.shape == tall.shape == (briefing.HEIGHT, briefing.WIDTH, 3)
    assert wide[:, 0].max() == 255         # a 16:9 page fills the width (white page)
    assert tall[:, :100].max() == 0         # a portrait page has black side bars
    assert tall[:, briefing.WIDTH // 2].max() == 255


def test_png_is_valid(tmp_path):
    pixels = np.zeros((4, 6, 3), dtype=np.uint8)
    pixels[1, 2] = (255, 0, 0)
    path = tmp_path / "x.png"
    briefing.write_png(pixels, str(path))
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82")


def test_subtitle_cues_split_long_text_in_proportion():
    text = "First sentence here. " + " ".join(["word"] * 40) + "."
    cues = briefing.subtitle_cues([(10.0, 20.0, text)])
    assert all(len(t) <= briefing.MAX_CUE_CHARS for _, _, t in cues)
    assert cues[0][2] == "First sentence here."
    assert cues[0][0] == 10.0 and cues[-1][1] == pytest.approx(20.0)
    assert all(a[1] == pytest.approx(b[0]) for a, b in zip(cues, cues[1:]))


def test_srt_format(tmp_path):
    path = tmp_path / "s.srt"
    briefing.write_srt([(0.0, 1.5, "Hi."), (3661.25, 3662.0, "Later.")], str(path))
    assert path.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,500\nHi.\n\n"
        "2\n01:01:01,250 --> 01:01:02,000\nLater.\n\n")


def test_frames_cover_the_hold():
    assert briefing.frames_for(1.0) == 30
    assert briefing.frames_for(1.01) == 31
    assert briefing.frames_for(0) == 1


def test_briefing_line_resolves_next_to_script(tmp_path):
    script = tmp_path / "s.md"
    assert g.briefing_pdf_path("**Briefing:** deck.pdf\n\nHi.", str(script)) == str(tmp_path / "deck.pdf")
    assert g.briefing_pdf_path("Hi.", str(script)) is None
    assert g.briefing_pdf_path("Hi.", str(script), cli_pdf="x.pdf") == "x.pdf"
    assert g.strip_markdown("**Briefing:** deck.pdf\n\nHi.") == "Hi."


def test_briefing_scripts_get_mp4_outputs(folders):
    inputs, outputs, _ = folders
    inputs.mkdir()
    (inputs / "talk.md").write_text("Hi.", encoding="utf-8")
    (inputs / "deck.md").write_text("**Briefing:** deck.pdf\n\n## Page 1\n\nHi.", encoding="utf-8")
    jobs = g.resolve_jobs(g.parse_args(["podcast-generator"]))
    assert sorted(o for _, o in jobs) == [str(outputs / "deck.mp4"), str(outputs / "talk.mp3")]


def test_pdf_flag_needs_a_script(capsys):
    assert g.run(g.parse_args(["podcast-generator", "--pdf", "d.pdf"])) == 1
    assert "--pdf needs a script" in capsys.readouterr().err


def test_page_count_mismatch_fails_before_synthesis(tmp_path):
    pdf = make_pdf(tmp_path / "deck.pdf", [("One", LANDSCAPE)])
    script = tmp_path / "deck.md"
    script.write_text("**Briefing:** deck.pdf\n\n## Page 1\n\nA.\n\n## Page 2\n\nB.", encoding="utf-8")
    engine = SpeechEngine()
    with pytest.raises(ValueError, match="the PDF has pages 1 to 1"):
        g.process_job(engine, str(script), str(tmp_path / "deck.mp4"), g.parse_args(["podcast-generator"]))
    assert engine.calls == []


def _probe(path, entries):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@needs_ffmpeg
def test_briefing_makes_synced_mp4_with_subtitles(tmp_path):
    make_pdf(tmp_path / "deck.pdf", [("One", LANDSCAPE), ("Two", PORTRAIT), ("Three", LANDSCAPE)])
    script = tmp_path / "deck.md"
    script.write_text(
        "# Deck\n**Briefing:** deck.pdf\n\n## Page 1\n\nHello there.\n\n"
        "## Page 3\n\nAnd goodbye.", encoding="utf-8")
    out = tmp_path / "out" / "deck.mp4"
    g.process_job(SpeechEngine(), str(script), str(out), g.parse_args(["podcast-generator"]))

    # Pages 1 and 3: 0.5 s speech + 0.75 s pause = 1.25 s -> 38 frames each;
    # page 2: a 3 s silent hold -> 90 frames. 166 frames in all.
    info = json.loads((tmp_path / "out" / "deck.briefing.json").read_text(encoding="utf-8"))
    assert [p["page"] for p in info["pages"]] == [1, 2, 3]
    assert [p["shown_seconds"] for p in info["pages"]] == [round(38 / 30, 3), 3.0, round(38 / 30, 3)]
    assert info["pdf_pages"] == 3 and info["total_seconds"] == round(166 / 30, 3)

    streams = _probe(out, "stream=codec_type,codec_name,width,height,nb_frames,duration")["streams"]
    kinds = {s["codec_type"]: s for s in streams}
    assert kinds["video"]["codec_name"] == "h264"
    assert (kinds["video"]["width"], kinds["video"]["height"]) == (1920, 1080)
    assert int(kinds["video"]["nb_frames"]) == 166
    assert float(kinds["audio"]["duration"]) == pytest.approx(166 / 30, abs=0.05)
    assert kinds["subtitle"]["codec_name"] == "mov_text"

    srt = (tmp_path / "out" / "deck.srt").read_text(encoding="utf-8")
    assert "Hello there." in srt and "And goodbye." in srt
    # Page 3 starts at frame 128 (38 + 90): 4.267 s.
    assert "00:00:04,267 --> 00:00:04,767\nAnd goodbye." in srt


@needs_ffmpeg
def test_watch_folder_briefing_archives_its_pdf(folders, monkeypatch):
    inputs, outputs, archive = folders
    inputs.mkdir()
    make_pdf(inputs / "deck.pdf", [("One", LANDSCAPE)])
    (inputs / "deck.md").write_text("**Briefing:** deck.pdf\n\n## Page 1\n\nHi.", encoding="utf-8")

    import voxport.tts.kokoro_direct as kd
    monkeypatch.setattr(kd, "KokoroDirectTTS", SpeechEngine)
    assert g.run(g.parse_args(["podcast-generator"])) == 0
    assert (outputs / "deck.mp4").exists()
    assert sorted(p.name for p in archive.iterdir()) == ["deck.md", "deck.pdf"]
    assert list(inputs.iterdir()) == []


def test_shared_pdf_stays_while_another_script_needs_it(folders):
    inputs, _, archive = folders
    inputs.mkdir()
    pdf = make_pdf(inputs / "deck.pdf", [("One", LANDSCAPE)])
    (inputs / "short.md").write_text("**Briefing:** deck.pdf\n\n## Page 1\n\nHi.", encoding="utf-8")
    assert g.archive_briefing_pdf(str(pdf)) is None
    (inputs / "short.md").unlink()
    assert g.archive_briefing_pdf(str(pdf)) == str(archive / "deck.pdf")
