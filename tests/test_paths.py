import os

from podcast_generator import paths


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("PODCAST_GENERATOR_HOME", str(tmp_path))
    assert paths.home_dir() == str(tmp_path)


def test_source_checkout_uses_repo(monkeypatch):
    monkeypatch.delenv("PODCAST_GENERATOR_HOME", raising=False)
    monkeypatch.setattr(paths, "is_source_checkout", lambda: True)
    assert paths.home_dir() == os.path.dirname(paths.PACKAGE_DIR)


def test_installed_package_uses_documents(monkeypatch, tmp_path):
    import platformdirs

    monkeypatch.delenv("PODCAST_GENERATOR_HOME", raising=False)
    monkeypatch.setattr(paths, "is_source_checkout", lambda: False)
    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(tmp_path))
    assert paths.home_dir() == os.path.join(str(tmp_path), "podcast_generator")


def test_watch_script_ships_in_package():
    assert os.path.isfile(os.path.join(paths.PACKAGE_DIR, "podcast-watch.ps1"))
