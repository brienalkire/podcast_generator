"""podcast_status, including wait_seconds."""
import asyncio
import time

import pytest

pytest.importorskip("mcp")

from podcast_generator import mcp_server as m  # noqa: E402


@pytest.fixture
def server(folders, monkeypatch):
    """Fast polling, no real scheduled-task or run-lock checks."""
    inputs, outputs, _ = folders
    inputs.mkdir()
    outputs.mkdir()
    monkeypatch.setattr(m, "STATUS_POLL_SECONDS", 0.05)
    monkeypatch.setattr(m, "_watch_state", lambda: "off")
    monkeypatch.setattr(m, "_converting", lambda: False)
    return inputs, outputs


def status(name, wait_seconds=0):
    return asyncio.run(m.podcast_status(name, wait_seconds))


def test_done_answers_at_once(server):
    _, outputs = server
    (outputs / "ep.mp3").write_bytes(b"")
    result = status("ep")
    assert result["status"] == "done"
    assert "waited_seconds" not in result


def test_wait_returns_when_conversion_finishes(server, monkeypatch):
    inputs, outputs = server
    (inputs / "ep.md").write_text("Hello.")
    checks = []

    def converting():
        checks.append(1)
        if len(checks) == 3:  # the run finishes: script archived, audio written
            (inputs / "ep.md").unlink()
            (outputs / "ep.mp3").write_bytes(b"")
            return False
        return True

    monkeypatch.setattr(m, "_converting", converting)
    result = status("ep", wait_seconds=30)
    assert result["status"] == "done"
    assert result["waited_seconds"] < 5


def test_wait_gives_up_after_wait_seconds(server, monkeypatch):
    inputs, _ = server
    (inputs / "ep.md").write_text("Hello.")
    monkeypatch.setattr(m, "_converting", lambda: True)
    start = time.monotonic()
    result = status("ep", wait_seconds=1)
    assert result["status"] == "converting"
    assert 0.9 <= time.monotonic() - start < 3


def test_queued_with_watch_off_does_not_wait(server):
    inputs, _ = server
    (inputs / "ep.md").write_text("Hello.")
    start = time.monotonic()
    result = status("ep", wait_seconds=50)
    assert result["status"] == "queued"
    assert time.monotonic() - start < 1


def test_queued_with_watch_on_waits(server, monkeypatch):
    inputs, _ = server
    (inputs / "ep.md").write_text("Hello.")
    monkeypatch.setattr(m, "_watch_state", lambda: "on")
    monkeypatch.setattr(m, "_watch_interval_minutes", lambda: 5)
    start = time.monotonic()
    result = status("ep", wait_seconds=1)
    assert result["status"] == "queued"
    assert time.monotonic() - start >= 0.9


def test_wait_is_capped(server, monkeypatch):
    inputs, _ = server
    (inputs / "ep.md").write_text("Hello.")
    monkeypatch.setattr(m, "_converting", lambda: True)
    monkeypatch.setattr(m, "MAX_WAIT_SECONDS", 1)
    start = time.monotonic()
    status("ep", wait_seconds=10_000)
    assert time.monotonic() - start < 3


def test_negative_wait_is_no_wait(server, monkeypatch):
    inputs, _ = server
    (inputs / "ep.md").write_text("Hello.")
    monkeypatch.setattr(m, "_converting", lambda: True)
    start = time.monotonic()
    assert status("ep", wait_seconds=-5)["status"] == "converting"
    assert time.monotonic() - start < 1
