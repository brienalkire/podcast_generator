import os
import tempfile

# podcast_generator.generator reads its home folder and .env at import time,
# so point it at an empty temporary folder before any test imports it, and
# make sure a developer's own folder settings can't leak in.
os.environ["PODCAST_GENERATOR_HOME"] = tempfile.mkdtemp(prefix="podcast_generator_test_")
for _key in ("PODCAST_INPUTS_DIR", "PODCAST_OUTPUTS_DIR", "PODCAST_ARCHIVE_DIR"):
    os.environ.pop(_key, None)

import pytest  # noqa: E402

from podcast_generator import generator as g  # noqa: E402


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """Fresh inputs/outputs/archive folders for one test."""
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    archive = tmp_path / "script_archive"
    monkeypatch.setattr(g, "INPUT_DIR", str(inputs))
    monkeypatch.setattr(g, "OUTPUT_DIR", str(outputs))
    monkeypatch.setattr(g, "ARCHIVE_DIR", str(archive))
    monkeypatch.setattr(g, "FAILED_DIR", str(archive / "failed"))
    return inputs, outputs, archive
