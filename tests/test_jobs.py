import os
import re

import pytest

from podcast_generator import generator as g


def args(*argv):
    return g.parse_args(["podcast-generator", *argv])


def test_batch_queues_every_script(folders):
    inputs, outputs, _ = folders
    inputs.mkdir()
    (inputs / "b.md").write_text("B")
    (inputs / "a.md").write_text("A")
    (inputs / "notes.txt").write_text("ignored")
    jobs = g.resolve_jobs(args())
    assert jobs == [
        (str(inputs / "a.md"), os.path.join(str(outputs), "a.mp3")),
        (str(inputs / "b.md"), os.path.join(str(outputs), "b.mp3")),
    ]


def test_empty_inputs_folder_is_not_an_error(folders):
    folders[0].mkdir()
    with pytest.raises(g.NoScriptsQueued):
        g.resolve_jobs(args())


def test_missing_default_inputs_folder_is_created(folders):
    inputs = folders[0]
    with pytest.raises(g.NoScriptsQueued, match="Created the inputs folder"):
        g.resolve_jobs(args())
    assert inputs.is_dir()


def test_missing_configured_inputs_folder_is_an_error(folders, monkeypatch):
    monkeypatch.setenv("PODCAST_INPUTS_DIR", str(folders[0]))
    with pytest.raises(FileNotFoundError):
        g.resolve_jobs(args())
    assert not folders[0].exists()


def test_single_file_honors_output(folders, tmp_path):
    script = tmp_path / "one.md"
    script.write_text("x")
    jobs = g.resolve_jobs(args(str(script), "--output", "ep.wav", "--format", "wav"))
    assert jobs == [(str(script), "ep.wav")]


def test_archive_moves_only_scripts_from_inputs(folders, tmp_path):
    inputs, _, archive = folders
    inputs.mkdir()
    queued = inputs / "q.md"
    queued.write_text("x")
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_text("x")

    assert g.archive_script(str(elsewhere)) is None
    assert elsewhere.exists()

    dest = g.archive_script(str(queued))
    assert dest == str(archive / "q.md")
    assert not queued.exists()


def test_failed_script_is_archived_with_its_error(folders):
    inputs, _, archive = folders
    inputs.mkdir()
    bad = inputs / "bad.md"
    bad.write_text("x")
    dest = g.archive_failed_script(str(bad), "boom")
    assert dest == str(archive / "failed" / "bad.md")
    assert (archive / "failed" / "bad.md.error.txt").read_text() == "boom"


def test_run_lock_is_exclusive():
    first = g.acquire_run_lock()
    assert first is not None
    try:
        assert g.acquire_run_lock() is None
        assert g.is_run_in_progress()
    finally:
        g.release_run_lock(first)
    assert not g.is_run_in_progress()


def test_idle_run_exits_cleanly(folders, capsys):
    folders[0].mkdir()
    assert g.main(["podcast-generator"]) == 0
    assert "No .md scripts found" in capsys.readouterr().out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        g.parse_args(["podcast-generator", "--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"podcast-generator {g.__version__}"


def test_wait_retries_the_run_lock(monkeypatch):
    attempts = []

    def acquire():
        attempts.append(1)
        return None if len(attempts) < 3 else "lock"

    monkeypatch.setattr(g, "acquire_run_lock", acquire)
    monkeypatch.setattr(g, "release_run_lock", lambda handle: None)
    monkeypatch.setattr(g, "WAIT_POLL_SECONDS", 0)
    monkeypatch.setattr(g, "run", lambda args: 0)
    assert g.main(["podcast-generator", "--wait"]) == 0
    assert len(attempts) == 3


def test_without_wait_a_busy_lock_leaves_the_queue(monkeypatch):
    monkeypatch.setattr(g, "acquire_run_lock", lambda: None)
    monkeypatch.setattr(g, "run", lambda args: pytest.fail("should not run"))
    assert g.main(["podcast-generator"]) == 0


def test_connector_runs_archive_repeated_names_with_a_timestamp(folders, monkeypatch, tmp_path):
    # A connector run points INPUT_DIR at the connector queue (see
    # mcp_server.generate_now); archiving then works as for the watch.
    queue = tmp_path / "connector_queue"
    queue.mkdir()
    monkeypatch.setattr(g, "INPUT_DIR", str(queue))
    archive = folders[2]
    archive.mkdir()
    (archive / "ep.md").write_text("first take")
    (queue / "ep.md").write_text("second take")
    dest = g.archive_script(str(queue / "ep.md"))
    assert re.fullmatch(r"ep_\d{8}_\d{6}\.md", os.path.basename(dest))
    assert (archive / "ep.md").read_text() == "first take"
    assert not (queue / "ep.md").exists()
