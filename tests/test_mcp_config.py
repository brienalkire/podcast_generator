"""`podcast-generator-mcp --config`: the Claude Desktop entry it prints."""
import json
import os
import sys

import pytest

pytest.importorskip("mcp")

from podcast_generator import mcp_server  # noqa: E402


def test_config_uses_full_command_path(tmp_path, monkeypatch):
    monkeypatch.delenv("PODCAST_GENERATOR_HOME", raising=False)
    exe = tmp_path / "bin" / "podcast-generator-mcp"
    entry = mcp_server.desktop_config(str(exe))["mcpServers"]["podcast-generator"]
    assert entry == {"command": str(exe)}


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher naming")
def test_config_adds_exe_on_windows(tmp_path, monkeypatch):
    monkeypatch.delenv("PODCAST_GENERATOR_HOME", raising=False)
    exe = tmp_path / "podcast-generator-mcp.exe"
    exe.write_bytes(b"")
    entry = mcp_server.desktop_config(str(tmp_path / "podcast-generator-mcp"))
    assert entry["mcpServers"]["podcast-generator"]["command"] == str(exe)


def test_config_for_python_m(monkeypatch):
    monkeypatch.delenv("PODCAST_GENERATOR_HOME", raising=False)
    entry = mcp_server.desktop_config(mcp_server.__file__)["mcpServers"]["podcast-generator"]
    assert entry == {"command": sys.executable,
                     "args": ["-m", "podcast_generator.mcp_server"]}


def test_config_passes_home_through(tmp_path, monkeypatch):
    monkeypatch.setenv("PODCAST_GENERATOR_HOME", str(tmp_path))
    entry = mcp_server.desktop_config("podcast-generator-mcp")["mcpServers"]["podcast-generator"]
    assert entry["env"] == {"PODCAST_GENERATOR_HOME": str(tmp_path)}


def test_main_config_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["podcast-generator-mcp", "--config"])
    assert mcp_server.main() == 0
    assert "podcast-generator" in json.loads(capsys.readouterr().out)["mcpServers"]


def test_main_rejects_unknown_args(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["podcast-generator-mcp", "--bogus"])
    assert mcp_server.main() == 2
    assert "usage" in capsys.readouterr().err
