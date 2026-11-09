import os

import pytest

mcp_server = pytest.importorskip("podcast_generator.mcp_server")


@pytest.fixture(autouse=True)
def no_watch(monkeypatch):
    monkeypatch.setattr(mcp_server, "_watch_state", lambda: "off")


def test_queue_dialogue_sets_voices_line(folders):
    result = mcp_server.queue_podcast(
        "talk", "# Talk\n\nMaya: Hi Theo.\n\nTheo: Hi Maya.",
        voices={"Maya": "af_heart", "Theo": ""})
    saved = (folders[0].parent / "connector_queue" / "talk.md").read_text(encoding="utf-8")
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


def test_queue_goes_to_connector_queue_not_watch_inputs(folders):
    mcp_server.queue_podcast("solo", "Hello there.")
    assert (folders[0].parent / "connector_queue" / "solo.md").is_file()
    assert not folders[0].exists()


def test_queue_refuses_name_waiting_in_watch_inputs(folders):
    folders[0].mkdir()
    (folders[0] / "mine.md").write_text("The user's own script.")
    with pytest.raises(mcp_server.ToolError, match="inputs folder"):
        mcp_server.queue_podcast("mine", "Hello.", replace=True)


def test_generate_now_converts_only_the_connector_queue(folders, monkeypatch):
    folders[0].mkdir()
    (folders[0] / "mine.md").write_text("The user's own script.")
    mcp_server.queue_podcast("solo", "Hello there.")
    started = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            started.update(cmd=cmd, env=kwargs["env"])

        def poll(self):
            return None

    monkeypatch.setattr(mcp_server.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(mcp_server, "_converting", lambda: True)
    monkeypatch.setattr(mcp_server.g, "open_log", lambda: open(os.devnull, "w"))
    result = mcp_server.generate_now()
    assert result["started"] and result["queued"] == ["solo.md"]
    assert "starts when it finishes" in result["note"]
    assert started["cmd"][-1] == "--wait"
    assert started["env"]["PODCAST_INPUTS_DIR"] == mcp_server.g.CONNECTOR_QUEUE_DIR
