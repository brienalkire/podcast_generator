# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `scripts/podcast-watch.ps1` and a single "Podcast Watch" desktop
  shortcut: one window to turn the `PodcastGeneratorWatch` task on/off,
  choose whether opening the app turns the watch on, off, or leaves it
  (`PODCAST_WATCH_ON_OPEN` in `.env`), and pick the inputs/outputs/archive
  folders (saved to `.env`; "Use default" returns to the repo's folders).
- Podcast Watch app: a **Set up watch** button that registers the
  `PodcastGeneratorWatch` task when it doesn't exist yet (current user, no
  admin rights, runs on battery too, uses `pythonw.exe` so no console window
  flashes up), and a **Check every** setting for the interval.
- Podcast Watch app: an **About** menu showing the version (read from
  `VERSION`) and the author.
- `mcp_server.py`: an MCP server so Claude Desktop or another MCP client can
  list voices, queue a script (validated up front), start a conversion in
  the background, check a podcast's status, list recent podcasts, and turn
  the watch on or off. Adds `mcp>=2.3,<3` to `requirements.txt`.
- `generator.py` takes a lock so only one conversion runs at a time on a
  machine; a run that finds another in progress leaves the queue to it.
  Under `pythonw.exe`, output goes to `generator.log` (rotated at 1 MB).

### Changed

- Depends on `voxport` (v0.3.0+), the renamed `vox_bridge` toolkit:
  import, setup docs and error message updated. Reinstall it
  (`pip uninstall vox_bridge`, then `pip install -e ../voxport`).
- voxport now comes from PyPI: `requirements.txt` lists
  `voxport[kokoro]>=0.5.0` (and `soundfile`, which voxport no longer
  installs), so a side-by-side voxport checkout is no longer needed.
  `generator.py` turns on voxport's progress logging (0.5.0 moved it from
  `print()` to `logging`). Offline-cache docs now use `HF_HOME` in `.env`.
- MANUAL.md: new "The Podcast Watch app" section with a screenshot
  (`docs/images/podcast-watch.png`), an expanded scheduled-mode overview,
  and troubleshooting entries for the app and the watch.
- `instructions_creating_podcast_generator.md` brought up to date (v5.0):
  `generator.py` instead of `tts_podcast.py`, `af_heart` default voice,
  configurable folders, archiving and `failed/`, drop-folder mode with the
  Podcast Watch app, `vox_bridge` setup, and the `hf_cache/` offline steps.

### Removed

- `scripts/watch-on.ps1` / `scripts/watch-off.ps1` and the two "Podcast
  Watch - Turn ON/OFF" shortcuts, replaced by the app above.

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
  [`vox_bridge`](../vox_bridge) toolkit's `KokoroDirectTTS`, replacing the
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

[Unreleased]: https://github.com/brienalkire/podcast_generator/commits/main
