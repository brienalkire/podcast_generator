import pytest

mcp_server = pytest.importorskip("podcast_generator.mcp_server")


@pytest.fixture(autouse=True)
def no_watch(monkeypatch):
    monkeypatch.setattr(mcp_server, "_watch_state", lambda: "off")


def test_queue_dialogue_sets_voices_line(folders):
    inputs = folders[0]
    result = mcp_server.queue_podcast(
        "talk", "# Talk\n\nMaya: Hi Theo.\n\nTheo: Hi Maya.",
        voices={"Maya": "af_heart", "Theo": ""})
    saved = (inputs / "talk.md").read_text(encoding="utf-8")
    assert "**Voices:** Maya=af_heart, Theo\n" in saved
    assert result["speakers"] == {"Maya": "af_heart", "Theo": "bm_george"}
    assert result["spoken_words"] == 4
    assert "warning" not in result


def test_queue_dialogue_warns_about_unheard_speaker(folders):
    result = mcp_server.queue_podcast(
        "talk2", "Maya: Hello.", voices={"Maya": "af_heart", "Theo": "bm_george"})
    assert "Theo:" in result["warning"]


def test_queue_rejects_unknown_speaker_voice(folders):
    with pytest.raises(mcp_server.ToolError, match="unknown voice"):
        mcp_server.queue_podcast("talk3", "Maya: Hi.", voices={"Maya": "zz_nobody"})


def test_list_podcasts_reports_version(folders, monkeypatch):
    monkeypatch.setattr(mcp_server, "_converting", lambda: False)
    assert mcp_server.list_podcasts()["version"] == mcp_server.g.__version__
