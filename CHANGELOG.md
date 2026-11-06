# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.4] - 2026-11-05

### Changed

- Requires voxport 0.5.1 or later, whose `kokoro` extra now depends on
  `pip` too (the same `en_core_web_sm` fix as 0.3.2, made where the Kokoro
  dependency comes from). podcast-generator keeps its own `pip`
  dependency as well.

## [0.3.3] - 2026-11-05

### Added

- MCP `podcast_status` takes an optional `wait_seconds` (up to 50): it waits
  for a queued or converting podcast to finish before answering, and
  returns as soon as it's done or failed, or at once if waiting can't
  change anything. AI clients no longer need their own way to pause
  between checks (Claude Desktop was reaching for other tools to do it).

### Changed

- Manual: the Claude Desktop section now covers checking the connector is
  installed, using it (example requests and what to expect on the first
  run), and upgrading, with troubleshooting for a Claude Desktop that won't
  quit, a partly applied upgrade, and the `en_core_web_sm` error.

## [0.3.2] - 2026-11-05

### Fixed

- First conversion in an environment without pip (such as
  `uv tool install`) failed with "Can't find model 'en_core_web_sm'":
  spaCy fell back to a `uv pip install` that put the model in a different
  environment. podcast-generator now depends on `pip`, so spaCy installs
  the model where it's needed.

## [0.3.1] - 2026-11-05

### Added

- `podcast-generator-mcp --config` prints the Claude Desktop
  (`claude_desktop_config.json`) entry for the current install, with the
  command's full path and `PODCAST_GENERATOR_HOME` if set.
  `podcast-generator-mcp --version` prints the version.

### Changed

- Claude Desktop setup in the README and manual now recommends a
  `uv tool install` / `pipx install`, so the command path stays valid, and
  uses `--config` instead of hand-written paths.

## [0.3.0] - 2026-11-02

First public release, and the first on PyPI (`pip install podcast-generator`).

### Added

- Packaged for PyPI as `podcast-generator`, with three commands:
  `podcast-generator` (convert scripts; also `python -m podcast_generator`),
  `podcast-generator-mcp` (the MCP server, with the `[mcp]` extra) and
  `podcast-watch` (the Podcast Watch app; `podcast-watch --shortcut` makes
  the desktop shortcut).
- A home folder for settings and the default folders: `podcast_generator`
  in Documents for a pip install, the repo for a source checkout, or
  `PODCAST_GENERATOR_HOME`. The first batch run creates the inputs folder.
- MCP server: Claude Desktop or another MCP client can list voices, queue a
  script (validated up front), start a conversion in the background, check
  a podcast's status, list recent podcasts, and turn the watch on or off.
- Podcast Watch app (Windows): one window to set up the
  `PodcastGeneratorWatch` scheduled task (current user, no admin rights,
  `pythonw.exe` so no window flashes up), turn it on or off, set how often
  it checks, choose what happens when the app opens
  (`PODCAST_WATCH_ON_OPEN`), and pick the inputs/outputs/archive folders.
  Its **About** menu shows the version and author.
- Only one conversion runs at a time on a machine; a run that finds
  another in progress leaves the queue to it. Under `pythonw.exe`, output
  goes to `generator.log` (rotated at 1 MB).
- Tests, GitHub Actions CI, and a tag-triggered workflow that publishes to
  PyPI and creates the GitHub release.
- MANUAL.md: sections on the Podcast Watch app, the home folder, offline
  use, and troubleshooting the app, the watch and the MCP server.

### Changed

- Speech synthesis comes from [`voxport`](https://pypi.org/project/voxport/)
  0.5.0+ on PyPI (the renamed `vox_bridge`), with its `kokoro` extra. Its
  progress messages (model loads, each segment) are shown through logging.
- The code moved into the `podcast_generator` package. `generator.py` and
  `mcp_server.py` at the repo root remain as thin wrappers, so scheduled
  tasks and MCP configs made before this release keep working.
- Offline use: point `HF_HOME` at a copied Hugging Face cache in `.env`,
  instead of voxport's repo `hf_cache/` folder.
- `instructions_creating_podcast_generator.md` brought up to date (v6.0).

### Removed

- `requirements.txt` (dependencies are in `pyproject.toml`) and `VERSION`
  (the version lives in `podcast_generator/__init__.py`).
- `scripts/watch-on.ps1` / `scripts/watch-off.ps1` and their two desktop
  shortcuts, replaced by the Podcast Watch app.

## Earlier versions

*Versions 0.1.0 to 0.2.1 predate this public repository, which starts
from a fresh history, so they have no tags or releases here.*

## 0.2.1 - 2026-10-31

### Fixed

- `generator.py --version` reported `0.1.0` in the v0.2.0 release.

### Changed

- README: new Installation and Usage sections. MANUAL.md now describes
  how italic-only lines at the top of a script are handled.

## 0.2.0 - 2026-10-31

### Added

- `scripts/watch-on.ps1` / `scripts/watch-off.ps1` and matching desktop
  shortcuts ("Podcast Watch - Turn ON/OFF") that enable/disable the
  `PodcastGeneratorWatch` scheduled task with a confirmation popup, so
  toggling the folder-watch schedule doesn't need PowerShell or Task
  Scheduler's GUI.
- `MANUAL.md`, a full user manual: script-writing guide, CLI reference,
  voice catalog, and troubleshooting.

### Removed

- The `reference/` folder and the obsolete in-repo `inputs/`/`outputs/`
  folders.

### Fixed

- An all-italic line near the top of a script (e.g. `*Source: ...*`) was
  treated as the end-of-script marker, so the whole script stripped to
  nothing and failed with "no spoken text found". Italic-only lines now end
  the script only after spoken prose has started; before that they're
  skipped as front matter.

## 0.1.0 - 2026-09-19

### Added

- `generator.py`: rebuilt as a consumer of the shared
  `vox_bridge` (now [`voxport`](https://github.com/brienalkire/voxport)) toolkit's `KokoroDirectTTS`, replacing the
  original standalone `tts_podcast.py` (which called Kokoro directly).
  Behavior preserved: same CLI flags (`--voice`, `--speed`, `--format`,
  `--output`), same markdown stripping, same per-script `**Voice:**`
  metadata handling and precedence rules.
- Configurable folder locations (`PODCAST_INPUTS_DIR`,
  `PODCAST_OUTPUTS_DIR`, `PODCAST_ARCHIVE_DIR` via `.env`), defaulting to
  local script-relative folders when unset. The same folders and the same
  command (`python generator.py`) serve both interactive use and scheduled/
  unattended runs — there is no separate watch-mode script.
- Archive-on-success: a successfully-converted script moves out of the
  inputs folder into the archive folder (collision-safe renamed if
  needed), so a rerun — manual or scheduled — never reprocesses it.
- Archive-on-failure: a script that fails to convert moves to
  `<archive>/failed/` with a `.error.txt` note, instead of being retried
  forever by a scheduled run.
- Job discovery happens before any heavy import (`vox_bridge`/`torch`/
  `kokoro`), so an empty inputs folder exits in a fraction of a second
  instead of paying model-load cost for nothing — the difference that
  makes polling this on a schedule cheap.
- `--version` flag.
- `LICENSE` (MIT).

### Changed

- Default voice changed from `am_onyx` to `af_heart` (actual usage:
  `af_heart` for most podcasts, `am_echo` via per-script `**Voice:**` for
  the military fellows program).
- An empty inputs queue now exits with code `0`, not `1` — it's the normal
  steady state for a scheduled/watched run, not an error. A genuinely
  missing inputs directory (misconfiguration) still exits `1`.

### Fixed

- Voice connect/permission and text/voice ordering issues live-tested and
  fixed on the `vox_bridge`/`loremaster` side of this work are recorded in
  those repos' own changelogs, not here — this file covers only
  `podcast_generator`.

[Unreleased]: https://github.com/brienalkire/podcast_generator/compare/v0.3.4...HEAD
[0.3.4]: https://github.com/brienalkire/podcast_generator/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/brienalkire/podcast_generator/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/brienalkire/podcast_generator/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/brienalkire/podcast_generator/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/brienalkire/podcast_generator/releases/tag/v0.3.0
