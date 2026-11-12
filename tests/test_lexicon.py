import pytest

from podcast_generator import generator as g
from test_dialogue import FakeEngine


def test_parse_lexicon_skips_comments_and_blanks():
    text = "﻿# acronyms\n\nJADC2 = J A D C two\nKokoro = [Kokoro](/kˈOkəɹO/)\n"
    assert g.parse_lexicon(text) == {
        "JADC2": "J A D C two", "Kokoro": "[Kokoro](/kˈOkəɹO/)"}


@pytest.mark.parametrize("line", ["JADC2", "= spoken", "JADC2 ="])
def test_parse_lexicon_reports_bad_line(line):
    with pytest.raises(ValueError, match="line 2"):
        g.parse_lexicon("# ok\n" + line, source="lex.txt")


def test_apply_lexicon_whole_word_case_sensitive():
    lexicon = {"JADC": "jad see", "JADC2": "J A D C two", "U.S.": "U S"}
    text = "JADC2 and JADC, not JADC2X or jadc2. The U.S. too."
    assert g.apply_lexicon(text, lexicon) == (
        "J A D C two and jad see, not JADC2X or jadc2. The U S too.")


def test_apply_lexicon_never_rewrites_a_replacement():
    assert g.apply_lexicon("AI", {"AI": "A I", "A": "ay"}) == "A I"


def test_load_lexicon_layers(tmp_path):
    user = tmp_path / "user.txt"
    user.write_text("A = user\nB = user\nC = user\n", encoding="utf-8")
    (tmp_path / "script.txt").write_text("B = script\nC = script\n", encoding="utf-8")
    cli = tmp_path / "cli.txt"
    cli.write_text("C = cli\n", encoding="utf-8")
    script = "**Lexicon:** script.txt\n\nHello."
    assert g.load_lexicon(script, str(tmp_path), str(cli), user_lexicon=str(user)) == {
        "A": "user", "B": "script", "C": "cli"}


def test_missing_user_lexicon_is_fine_but_named_one_is_not(tmp_path):
    assert g.load_lexicon("Hello.", str(tmp_path), user_lexicon=str(tmp_path / "none.txt")) == {}
    with pytest.raises(ValueError, match="not found"):
        g.load_lexicon("**Lexicon:** gone.txt\n\nHello.", str(tmp_path))


def test_lexicon_line_is_not_spoken():
    assert g.strip_markdown("**Lexicon:** terms.txt\n\nHello.") == "Hello."


def test_process_job_applies_lexicon_after_cleanup(tmp_path, monkeypatch):
    (tmp_path / "terms.txt").write_text("Kokoro = [Kokoro](/kˈOkəɹO/)\n", encoding="utf-8")
    script = tmp_path / "ep.md"
    script.write_text("**Lexicon:** terms.txt\n\nMeet **Kokoro** today.", encoding="utf-8")
    monkeypatch.setattr(g, "write_audio", lambda *a: None)
    engine = FakeEngine()
    g.process_job(engine, str(script), str(tmp_path / "ep.mp3"), g.parse_args(["podcast-generator"]))
    assert engine.calls[0][0] == "Meet [Kokoro](/kˈOkəɹO/) today."


def test_bad_user_lexicon_fails_run_without_archiving(folders, monkeypatch, capsys):
    inputs, _, archive = folders
    inputs.mkdir()
    (inputs / "ep.md").write_text("Hello.", encoding="utf-8")
    bad = inputs.parent / "lexicon.txt"
    bad.write_text("no equals sign\n", encoding="utf-8")
    monkeypatch.setattr(g, "LEXICON_PATH", str(bad))
    assert g.run(g.parse_args(["podcast-generator"])) == 1
    assert "line 1" in capsys.readouterr().err
    assert (inputs / "ep.md").exists() and not archive.exists()
