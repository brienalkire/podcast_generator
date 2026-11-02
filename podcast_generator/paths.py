"""Where podcast_generator keeps its settings and folders.

Everything lives in one "home" folder: `.env` (settings), the default
`inputs/`, `outputs/` and `script_archive/` folders, `generator.log` and the
run lock. Which folder that is, first match wins:

1. `PODCAST_GENERATOR_HOME`, if set (an environment variable; it can't go
   in `.env`, because `.env` lives in the home folder).
2. The repo folder, when running from a source checkout (the package sits
   next to a `pyproject.toml`). Keeps a clone self-contained.
3. `podcast_generator` in your Documents folder, for a regular pip install.

The folders themselves can still be pointed elsewhere with
PODCAST_INPUTS_DIR, PODCAST_OUTPUTS_DIR and PODCAST_ARCHIVE_DIR in `.env`.
Nothing here creates folders; callers create what they need.
"""

import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.dirname(PACKAGE_DIR)


def is_source_checkout() -> bool:
    return os.path.isfile(os.path.join(_REPO_DIR, "pyproject.toml"))


def home_dir() -> str:
    override = os.environ.get("PODCAST_GENERATOR_HOME")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if is_source_checkout():
        return _REPO_DIR
    from platformdirs import user_documents_dir
    return os.path.join(user_documents_dir(), "podcast_generator")
