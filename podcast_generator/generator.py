"""
podcast_generator.generator: the `podcast-generator` command.

Convert markdown podcast scripts into spoken-word audio files, using
`KokoroDirectTTS` from `voxport` (https://pypi.org/project/voxport/)
for the actual speech synthesis. No API key is required and no data leaves
your machine (beyond an optional, one-time Kokoro model download).

The script reads a markdown file, strips markdown formatting, the metadata
header block, and non-spoken section labels (e.g. OPENING, PART ONE, CLOSING),
then synthesizes speech locally and saves the result as an audio file.

Three ways to run this:

Manual CLI (batch mode, default):
    Place one or more `.md` scripts in the inputs folder and run the script
    with no arguments. Every script is converted, the audio lands in the
    outputs folder, and each successfully-converted script is moved into the
    archive folder (so a later run doesn't reprocess it).

        podcast-generator
        podcast-generator --voice af_heart --speed 1.1

Scheduled / "drop folder" mode:
    There's no separate watch-mode script — running the batch command above
    on a recurring schedule (e.g. Windows Task Scheduler) against a folder
    that syncs to the cloud (via Sync.com, Dropbox, etc.) *is* watch mode.
    A run that finds nothing to do exits almost immediately (jobs are
    discovered before any heavy import), so scheduling it every 10-15
    minutes costs essentially nothing when the inputs folder is empty. The
    Podcast Watch app (`podcast-watch`) sets up the Windows scheduled task.

Single-file mode:
    Pass a path to one script to convert just that file. The audio still
    lands in the outputs folder by default, or wherever --output points.
    Archiving still applies if the file happens to live in the inputs
    folder; a file named from elsewhere is left where it is.

        podcast-generator path/to/my-script.md
        podcast-generator my-script.md --format wav --output episode01.wav

Per-script voice:
    A script may choose its own voice with a metadata line anywhere in its
    header, e.g.

        **Voice:** af_heart

    Voice precedence is: a `--voice` given on the command line (applies to the
    whole run) overrides everything; otherwise a script's `**Voice:**` line is
    used; otherwise the default voice. The `--lang` accent code is derived
    automatically from the voice's first letter unless you pass `--lang`.

Folder locations:
    Default to `inputs/`, `outputs/`, `script_archive/` in the home folder
    (see paths.py: Documents/podcast_generator for a pip install, the repo
    for a source checkout). Override with the Podcast Watch app, or via the
    home folder's `.env` file (see `.env.example`) with PODCAST_INPUTS_DIR,
    PODCAST_OUTPUTS_DIR, PODCAST_ARCHIVE_DIR — e.g. pointed at a folder
    mirrored by a cloud sync client, so scripts dropped remotely get picked
    up and the finished audio syncs back out. The same folders are used
    whether this runs manually or on a schedule.

Requirements:
    - Python 3.10+ and this package's dependencies, including
      voxport[kokoro]: see README.md.
    - Recommended: espeak-ng installed on your system for best pronunciation
      of unusual words and numbers.
    - For MP3 output: either a recent `soundfile`/libsndfile build with MP3
      support, or `ffmpeg` available on your PATH. WAV needs neither.

Defaults:
    Voice: af_heart  (American female)
    Language: derived from the voice (a = American, b = British)
    Speed: 1.0
    Format: mp3
"""

import argparse
import glob
import logging
import os
import shutil
import sys
import re
import time
from datetime import datetime

from dotenv import load_dotenv

from . import __version__
from .paths import home_dir

# Settings, default folders, log and lock all live in the home folder.
HOME_DIR = home_dir()
ENV_PATH = os.path.join(HOME_DIR, ".env")
load_dotenv(ENV_PATH)

DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
DEFAULT_FORMAT = "mp3"
FORMAT_CHOICES = ["mp3", "wav"]

# Folder locations are configurable (e.g. to point at a cloud-synced
# "drop folder") via .env; all default to folders in the home folder so
# the tool works with zero configuration out of the box. The same folders
# are used for both manual CLI runs and scheduled/unattended runs.
INPUT_DIR = os.environ.get("PODCAST_INPUTS_DIR") or os.path.join(HOME_DIR, "inputs")
OUTPUT_DIR = os.environ.get("PODCAST_OUTPUTS_DIR") or os.path.join(HOME_DIR, "outputs")
ARCHIVE_DIR = os.environ.get("PODCAST_ARCHIVE_DIR") or os.path.join(HOME_DIR, "script_archive")
FAILED_DIR = os.path.join(ARCHIVE_DIR, "failed")
# Scripts queued by the MCP connector (podcast-generator-mcp) wait here, not
# in the inputs folder, so the folder watch never converts them and a
# connector run never converts the user's own drop-folder scripts. The
# connector converts this folder by running the generator with
# PODCAST_INPUTS_DIR pointed at it; finished scripts share ARCHIVE_DIR.
CONNECTOR_QUEUE_DIR = (os.environ.get("PODCAST_CONNECTOR_QUEUE_DIR")
                       or os.path.join(HOME_DIR, "connector_queue"))

# Only one conversion run at a time on this machine. Without this, a manual
# or MCP-started run overlapping a scheduled one would convert the same
# scripts twice and trip over each other's archiving. The OS releases the
# lock automatically if a run crashes, so a stale lock file is harmless.
LOCK_PATH = os.path.join(HOME_DIR, ".generator.lock")
# --wait: how long to wait for another run to finish, and how often to check.
WAIT_FOR_RUN_MINUTES = 120
WAIT_POLL_SECONDS = 5

# Where output goes when there's no console (pythonw.exe, which the
# scheduled task uses so no window flashes up), and for MCP-started runs.
LOG_PATH = os.path.join(HOME_DIR, "generator.log")
OLD_LOG_PATH = os.path.join(HOME_DIR, "generator.old.log")
LOG_MAX_BYTES = 1_000_000


def acquire_run_lock():
    """Return an open handle holding the run lock, or None if it's taken."""
    os.makedirs(HOME_DIR, exist_ok=True)
    handle = open(LOCK_PATH, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def release_run_lock(handle):
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    handle.close()


def is_run_in_progress():
    """True if another process is converting right now."""
    handle = acquire_run_lock()
    if handle is None:
        return True
    release_run_lock(handle)
    return False


def open_log():
    """Open LOG_PATH for appending, rotating it once it passes LOG_MAX_BYTES."""
    os.makedirs(HOME_DIR, exist_ok=True)
    try:
        if os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            os.replace(LOG_PATH, OLD_LOG_PATH)
    except OSError:
        pass
    return open(LOG_PATH, "a", encoding="utf-8", buffering=1)


def redirect_output_if_windowless():
    """Under pythonw.exe there's no stdout/stderr; send both to the log.

    Returns True if output was redirected.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return False
    log = open_log()
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log
    return True

# A selection of Kokoro voices. The first letter is the language/accent
# ('a' American, 'b' British), the second is gender ('m' male, 'f' female).
# This list drives the --help text and the choices check; see the Kokoro
# documentation for the full, current voice list.
VOICE_CHOICES = [
    # American male
    "am_onyx", "am_adam", "am_echo", "am_eric", "am_fenrir",
    "am_liam", "am_michael", "am_puck",
    # American female
    "af_heart", "af_bella", "af_nova", "af_sarah", "af_sky",
    "af_nicole", "af_aoede", "af_kore",
    # British male
    "bm_george", "bm_lewis", "bm_daniel", "bm_fable",
    # British female
    "bf_emma", "bf_isabella", "bf_alice", "bf_lily",
]

# A per-script voice line, e.g.  **Voice:** af_heart  (case-insensitive key).
# This line is also stripped from the spoken text by strip_markdown() because
# it matches the general **Key:** metadata pattern.
voice_meta_pattern = re.compile(
    r"^\s*\*\*\s*Voice\s*:\s*\*\*\s*([A-Za-z]{2}_[A-Za-z0-9]+)\s*$",
    re.IGNORECASE,
)


def parse_voice_metadata(raw_text):
    """Return the voice named in a `**Voice:** <voice>` line, or None.

    The first such line in the script wins.
    """
    for line in raw_text.splitlines():
        match = voice_meta_pattern.match(line)
        if match:
            return match.group(1)
    return None


def resolve_voice(raw_text, cli_voice):
    """Pick the voice for one script.

    Precedence: an explicit --voice (whole run) > the script's **Voice:** line
    > the built-in default. Raises ValueError if a script names an unknown
    voice.
    """
    if cli_voice:
        return cli_voice

    meta_voice = parse_voice_metadata(raw_text)
    if meta_voice:
        if meta_voice not in VOICE_CHOICES:
            raise ValueError(
                f"script requests unknown voice '{meta_voice}'. Valid voices: "
                f"{', '.join(VOICE_CHOICES)}."
            )
        return meta_voice

    return DEFAULT_VOICE


# A dialogue script names its speakers, and optionally their voices, e.g.
#   **Voices:** Maya=af_heart, Theo=bm_george
# Lines starting "Maya:" (or "**Maya:**") are then spoken in Maya's voice.
voices_meta_pattern = re.compile(r"^\s*\*\*\s*Voices\s*:\s*\*\*\s*(.*?)\s*$", re.IGNORECASE)
SPEAKER_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9 .'_-]{0,39}$")
# Voices given, in this order, to speakers listed without one. Alternating
# accent and gender keeps neighbouring speakers easy to tell apart.
DIALOGUE_VOICES = ["af_heart", "bm_george", "am_michael", "bf_emma",
                   "am_echo", "bf_isabella", "af_bella", "bm_lewis"]
# Silence between one speaker's turn and the next.
TURN_PAUSE_SECONDS = 0.35


def parse_voices_metadata(raw_text):
    """Return {speaker: voice or None} from a script's **Voices:** line.

    Returns {} when there is no such line (a single-narrator script). Raises
    ValueError for a malformed line or an unknown voice.
    """
    for line in raw_text.splitlines():
        match = voices_meta_pattern.match(line)
        if match:
            break
    else:
        return {}

    speakers = {}
    for item in match.group(1).split(","):
        if not item.strip():
            continue
        name, _, voice = item.partition("=")
        name, voice = name.strip(), voice.strip() or None
        if not SPEAKER_NAME_PATTERN.match(name):
            raise ValueError(
                f"the **Voices:** line has an unusable speaker name '{name}'. "
                f"Write it like: **Voices:** Maya=af_heart, Theo=bm_george"
            )
        if name.lower() in (known.lower() for known in speakers):
            raise ValueError(f"the **Voices:** line names '{name}' twice.")
        if voice and voice not in VOICE_CHOICES:
            raise ValueError(
                f"script gives {name} unknown voice '{voice}'. Valid voices: "
                f"{', '.join(VOICE_CHOICES)}."
            )
        speakers[name] = voice
    if not speakers:
        raise ValueError(
            "the **Voices:** line names no speakers. Write it like: "
            "**Voices:** Maya=af_heart, Theo=bm_george"
        )
    return speakers


def resolve_speaker_voices(raw_text):
    """Return {speaker: voice} for a dialogue script, or {} for a single narrator.

    Speakers listed without a voice get the next unused one from
    DIALOGUE_VOICES. Raises ValueError like parse_voices_metadata().
    """
    speakers = parse_voices_metadata(raw_text)
    unused = [v for v in DIALOGUE_VOICES if v not in speakers.values()]
    resolved = {}
    for index, (name, voice) in enumerate(speakers.items()):
        if not voice:
            voice = unused.pop(0) if unused else DIALOGUE_VOICES[index % len(DIALOGUE_VOICES)]
        resolved[name] = voice
    return resolved


def _speaker_label_pattern(speakers):
    """Match "Name: text", "**Name:** text" or "**Name**: text" for known names."""
    names = "|".join(re.escape(n) for n in sorted(speakers, key=len, reverse=True))
    return re.compile(
        rf"^\s*(?:\*\*)?\s*(?P<name>{names})\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*(?P<text>.*)$",
        re.IGNORECASE,
    )


# A briefing script's page marker:  ## Page 3  or  ## Page 3 (skip). Any
# header level works; the words are what's checked.
page_marker_pattern = re.compile(r"^#{1,6}\s*Page\s+(\d+)\s*(\(\s*skip\s*\))?\s*$", re.IGNORECASE)
# A header that was probably meant as a marker ("## Slide 3", "## Page three"),
# refused in a briefing rather than silently dropped.
near_page_marker_pattern = re.compile(r"^#{1,6}\s*(Page|Slide)\b", re.IGNORECASE)


class PageMarker:
    """A `## Page N` line, yielded by _spoken_lines(pages=True)."""

    def __init__(self, number, skip=False):
        self.number = number
        self.skip = skip

    def __repr__(self):
        return f"PageMarker({self.number}{', skip' if self.skip else ''})"


def _spoken_lines(raw_text, speakers=(), pages=False):
    """Yield (speaker, line) for each line of the script that is spoken.

    `speaker` is None for narration. With `speakers` (a dialogue script), a
    line starting with a speaker's label switches to that speaker, and the
    label itself is dropped; lines without a label continue the current
    speaker. Blank lines are yielded as "" so paragraph breaks survive.

    With `pages` (a briefing script), a `## Page N` header is yielded as
    (speaker, PageMarker) instead of being dropped, and a header that looks
    like a mistyped marker raises ValueError. The speaker and the
    end-of-script rule carry across markers, as in one long script.
    """
    # A metadata line looks like:  **Author:** Brien Alkire
    metadata_pattern = re.compile(r"^\s*\*\*[^*]+:\*\*")
    # A horizontal rule:  ---  or  ***  or  ___  (3 or more)
    hrule_pattern = re.compile(r"^\s*([-*_])\1{2,}\s*$")
    # A line that is entirely italic, e.g.  *End of script.*  (production note)
    italic_only_pattern = re.compile(r"^\s*\*[^*]+\*\s*$")
    # A bold-only line with no lowercase letters, e.g.  **INTRO**  (a section
    # label written in bold instead of as a header).
    bold_label_pattern = re.compile(r"^\s*\*\*([^*a-z]+)\*\*\s*$")
    label_pattern = _speaker_label_pattern(speakers) if speakers else None
    canonical = {name.lower(): name for name in speakers}
    speaker = None
    seen_prose = False

    for line in raw_text.splitlines():
        stripped = line.strip()

        # Keep blank lines for now; paragraph breaks are reconstructed later.
        if not stripped:
            yield speaker, ""
            continue

        # An all-italic line is a production note. After the prose starts it
        # is the end-of-script marker, so trailing notes/appendices are not
        # spoken; before that it's front matter like *Source: ...* and is
        # just skipped (otherwise the whole script would come out empty).
        if italic_only_pattern.match(stripped):
            if seen_prose:
                return
            continue

        # Drop markdown headers (#, ##, ###, ...). In these scripts the
        # section labels (OPENING, PART ONE, CLOSING, etc.) are headers,
        # so this also removes the spoken-aloud section labels.
        if stripped.startswith("#"):
            if pages:
                marker = page_marker_pattern.match(stripped)
                if marker:
                    yield speaker, PageMarker(int(marker.group(1)), bool(marker.group(2)))
                elif near_page_marker_pattern.match(stripped):
                    raise ValueError(
                        f"'{stripped}' isn't a page marker. Write it as "
                        f"'## Page N' (or '## Page N (skip)'), with N the PDF "
                        f"page number.")
            continue

        # Drop horizontal rules and bold section labels.
        if hrule_pattern.match(stripped) or bold_label_pattern.match(stripped):
            continue

        # A speaker's label. Checked before metadata, since "**Maya:** Hi"
        # looks like a metadata line too.
        if label_pattern:
            match = label_pattern.match(line)
            if match:
                speaker = canonical[match.group("name").lower()]
                if match.group("text").strip():
                    yield speaker, match.group("text")
                    seen_prose = True
                continue

        # Drop metadata key/value lines (Author, Date, Version, Voice, etc.).
        if metadata_pattern.match(stripped):
            continue

        yield speaker, line
        seen_prose = True


def _clean_inline(text):
    """Strip inline markdown from spoken lines and tidy the blank lines."""
    # Bold + italic markers.
    # Bold + italic markers.
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)   # **bold**
    text = re.sub(r"__([^_]+)__", r"\1", text)         # __bold__
    text = re.sub(r"\*([^*]+)\*", r"\1", text)          # *italic*
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", text)  # _italic_
    # Inline code: `code` -> code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Links: [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Collapse runs of blank lines into a single blank line, and trim.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_markdown(raw_text, speakers=()):
    """Strip markdown formatting, metadata, and section labels from the script.

    Returns clean prose suitable for text-to-speech: only the words that
    should actually be spoken aloud. Pass a dialogue script's `speakers`
    to keep its labelled lines (without the labels).
    """
    return _clean_inline("\n".join(line for _, line in _spoken_lines(raw_text, speakers)))


def split_turns(raw_text, speakers):
    """Split a dialogue script into [(speaker or None, spoken text), ...].

    Consecutive lines from the same speaker form one turn. None is the
    narrator, for any text before the first speaker label.
    """
    return _group_turns(_spoken_lines(raw_text, speakers))


def _group_turns(lines):
    """Join (speaker, line) pairs into cleaned [(speaker, text), ...] turns."""
    turns = []
    for speaker, line in lines:
        if turns and turns[-1][0] == speaker:
            turns[-1][1].append(line)
        else:
            turns.append((speaker, [line]))
    cleaned = [(speaker, _clean_inline("\n".join(lines))) for speaker, lines in turns]
    return [(speaker, text) for speaker, text in cleaned if text]


# Briefing timing: the pause after each page's narration before the next
# page, the hold for a page with nothing to say, and the section length
# (in words, about two minutes) that earns a "very long" warning.
INTER_PAGE_PAUSE_SECONDS = 0.75
SILENT_HOLD_SECONDS = 3.0
LONG_SECTION_WORDS = 350


def has_page_markers(raw_text):
    """True if any line of the script is a `## Page N` marker."""
    return any(page_marker_pattern.match(line.strip()) for line in raw_text.splitlines())


def split_pages(raw_text, speakers=()):
    """Split a briefing script into [(PageMarker, turns), ...] in script order.

    `turns` is [(speaker or None, text), ...] as from split_turns(). Raises
    ValueError for spoken text before the first marker or a mistyped
    marker. Doesn't check the page numbers; see plan_pages().
    """
    sections = []
    before_first = []
    for speaker, line in _spoken_lines(raw_text, speakers, pages=True):
        if isinstance(line, PageMarker):
            sections.append((line, []))
        elif sections:
            sections[-1][1].append((speaker, line))
        elif line.strip():
            before_first.append(line.strip())
    # With no markers at all, plan_pages() explains how to add them.
    if before_first and sections:
        raise ValueError(
            f"text before the first '## Page N' marker has no page to be "
            f"shown on: \"{before_first[0][:60]}\". Move it under a marker.")
    return [(marker, _group_turns(lines)) for marker, lines in sections]


def plan_pages(sections, page_count=None):
    """Check a briefing's sections and return (pages, warnings).

    `pages` is [(page number, turns), ...] for every page that's shown, in
    order; empty `turns` means a silent hold. With `page_count` unknown
    (None), pages run to the highest marker. Raises ValueError listing
    every problem that stops the briefing: no markers, a page that doesn't
    exist, or pages out of order or repeated.
    """
    if not sections:
        known = f"The PDF has {page_count} pages. " if page_count else ""
        raise ValueError(
            f"no '## Page N' markers found. {known}Start each page's narration "
            f"with a line like '## Page 1', numbered as in the PDF.")

    errors, warnings = [], []
    previous = 0
    for marker, _ in sections:
        n = marker.number
        if n < 1 or (page_count and n > page_count):
            errors.append(f"'## Page {n}': the PDF has pages 1 to {page_count}."
                          if page_count else f"'## Page {n}': pages start at 1.")
        elif n == previous:
            errors.append(f"page {n} has two sections.")
        elif n < previous:
            errors.append(f"page {n} comes after page {previous}; "
                          "sections must be in page order.")
        previous = max(previous, n)
    if errors:
        raise ValueError("this briefing can't be converted:\n- " + "\n- ".join(errors))

    by_page = {marker.number: (marker, turns) for marker, turns in sections}
    last = page_count or max(by_page)
    pages = []
    for n in range(1, last + 1):
        marker, turns = by_page.get(n, (None, []))
        if marker and marker.skip:
            if turns:
                warnings.append(f"page {n} is marked (skip), so its text isn't spoken.")
            continue
        words = sum(len(text.split()) for _, text in turns)
        if marker is None:
            warnings.append(f"page {n} has no section; it's shown silently for "
                            f"{SILENT_HOLD_SECONDS:g} s.")
        elif not words:
            warnings.append(f"page {n}'s section is empty; it's shown silently for "
                            f"{SILENT_HOLD_SECONDS:g} s.")
        elif words > LONG_SECTION_WORDS:
            warnings.append(f"page {n}'s section is {words} words, a long time "
                            "to show one page.")
        pages.append((n, turns))
    if not pages:
        raise ValueError("every page is marked (skip), so there's nothing to show.")
    return pages, warnings


def spoken_text(raw_text):
    """All the words a script will speak, for either kind of script."""
    speakers = resolve_speaker_voices(raw_text)
    if speakers:
        return "\n\n".join(text for _, text in split_turns(raw_text, speakers))
    return strip_markdown(raw_text)


# Pronunciation fixes: lines of  written form = spoken form  in a plain-text
# lexicon file. The user-level file holds standing terms; a script can add
# its own with a  **Lexicon:** file.txt  line, and --lexicon adds one more
# for a run. Later layers win for the same written form.
LEXICON_PATH = os.path.join(HOME_DIR, "lexicon.txt")
lexicon_meta_pattern = re.compile(r"^\s*\*\*\s*Lexicon\s*:\s*\*\*\s*(.*?)\s*$", re.IGNORECASE)


def parse_lexicon(text, source="lexicon"):
    """Return {written: spoken} from lexicon file text.

    One entry per line, `written = spoken`; blank lines and lines starting
    with `#` are ignored. Raises ValueError naming the line for a malformed
    entry.
    """
    entries = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip().lstrip("﻿")
        if not stripped or stripped.startswith("#"):
            continue
        written, sep, spoken = stripped.partition("=")
        written, spoken = written.strip(), spoken.strip()
        if not sep or not written or not spoken:
            raise ValueError(
                f"{source}, line {number}: expected 'written form = spoken form', "
                f"got: {stripped}")
        entries[written] = spoken
    return entries


def read_lexicon_file(path):
    """Parse the lexicon file at `path`. Raises ValueError if it's missing."""
    if not os.path.isfile(path):
        raise ValueError(f"lexicon file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return parse_lexicon(f.read(), source=path)


def parse_lexicon_metadata(raw_text):
    """Return the file named in a script's `**Lexicon:** <file>` line, or None."""
    for line in raw_text.splitlines():
        match = lexicon_meta_pattern.match(line)
        if match and match.group(1):
            return match.group(1)
    return None


def load_lexicon(raw_text, script_dir, cli_lexicon=None, user_lexicon=None):
    """Merge the lexicons that apply to one script.

    Layers, later winning: the user-level file (LEXICON_PATH, skipped if it
    doesn't exist), the script's **Lexicon:** file (relative to
    `script_dir`), then `cli_lexicon`. A named file that's missing, or any
    malformed file, raises ValueError.
    """
    user_lexicon = LEXICON_PATH if user_lexicon is None else user_lexicon
    entries = {}
    if user_lexicon and os.path.isfile(user_lexicon):
        entries.update(read_lexicon_file(user_lexicon))
    script_lexicon = parse_lexicon_metadata(raw_text)
    if script_lexicon:
        entries.update(read_lexicon_file(os.path.join(script_dir, script_lexicon)))
    if cli_lexicon:
        entries.update(read_lexicon_file(cli_lexicon))
    return entries


def apply_lexicon(text, lexicon):
    """Replace each whole-word, case-sensitive written form with its spoken form.

    One pass, longest forms first, so a replacement is never itself
    replaced and "JADC2" wins over "JADC". "Whole word" means not touching
    a letter, digit or underscore on either side, so forms like "U.S." work.
    """
    if not lexicon:
        return text
    forms = sorted(lexicon, key=len, reverse=True)
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(f) for f in forms) + r")(?!\w)")
    return pattern.sub(lambda m: lexicon[m.group(0)], text)


def write_audio(full_audio, out_path, fmt, sample_rate):
    """Write `full_audio` to `out_path` in the requested format.

    WAV is written directly. MP3 is attempted via libsndfile's native encoder
    first, falling back to converting a temporary WAV with ffmpeg.
    """
    import soundfile as sf

    if fmt == "wav":
        sf.write(out_path, full_audio, sample_rate)
        return

    # MP3: try libsndfile's native MP3 encoder first.
    try:
        sf.write(out_path, full_audio, sample_rate, format="MP3")
        return
    except Exception:  # noqa: BLE001 - libsndfile may lack MP3 support
        pass

    # Fall back to writing a WAV and converting with ffmpeg.
    import subprocess
    import tempfile

    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "Could not write MP3: the installed libsndfile lacks MP3 support "
            "and ffmpeg was not found on PATH. Install ffmpeg, or rerun with "
            "--format wav."
        )

    fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        sf.write(tmp_wav, full_audio, sample_rate)
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_wav, out_path],
            check=True, capture_output=True,
        )
    finally:
        try:
            os.remove(tmp_wav)
        except OSError:
            pass


def _unique_destination(directory, filename):
    """Return a collision-free path for `filename` inside `directory`."""
    dest = os.path.join(directory, filename)
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(filename)
    return os.path.join(directory, f"{base}_{datetime.now():%Y%m%d_%H%M%S}{ext}")


def archive_script(input_path):
    """Move a successfully-processed script out of INPUT_DIR into ARCHIVE_DIR.

    Only applies to scripts that actually live in INPUT_DIR — an explicitly
    named file from elsewhere (single-file mode) is left in place. This is
    what makes batch/scheduled runs safe to repeat: a processed script is
    gone from INPUT_DIR by the time the next run looks.
    """
    if os.path.dirname(os.path.abspath(input_path)) != os.path.abspath(INPUT_DIR):
        return None
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    dest = _unique_destination(ARCHIVE_DIR, os.path.basename(input_path))
    shutil.move(input_path, dest)
    return dest


def archive_failed_script(input_path, error_message):
    """Move a script that failed to convert into ARCHIVE_DIR/failed/.

    Same INPUT_DIR-only restriction as archive_script(). Without this, a
    script that can never succeed (e.g. an unknown **Voice:**) would be
    retried forever by a scheduled run.
    """
    if os.path.dirname(os.path.abspath(input_path)) != os.path.abspath(INPUT_DIR):
        return None
    os.makedirs(FAILED_DIR, exist_ok=True)
    dest = _unique_destination(FAILED_DIR, os.path.basename(input_path))
    shutil.move(input_path, dest)
    with open(dest + ".error.txt", "w", encoding="utf-8") as f:
        f.write(error_message)
    return dest


class NoScriptsQueued(Exception):
    """The inputs directory exists but currently has no .md scripts.

    Not an error: batch/scheduled runs treat an empty queue as the normal
    steady state (see main()), distinct from a real misconfiguration like a
    missing inputs directory, which still raises plain FileNotFoundError.
    """


def resolve_jobs(args):
    """Return a list of (input_path, output_path) tuples to process.

    With no positional argument, every `*.md` file in INPUT_DIR is queued.
    With a path argument, only that single file is queued. Output paths land
    in OUTPUT_DIR by default; `--output` overrides that in single-file mode.
    """
    fmt = args.response_format

    if args.input_path:
        inputs = [args.input_path]
    else:
        if not os.path.isdir(INPUT_DIR):
            # First run: make the folder so the user knows where scripts go.
            # A configured folder that's missing (e.g. an unmounted drive)
            # is still an error rather than silently recreated.
            if os.environ.get("PODCAST_INPUTS_DIR"):
                raise FileNotFoundError(
                    f"The inputs folder set by PODCAST_INPUTS_DIR does not "
                    f"exist: {INPUT_DIR}"
                )
            os.makedirs(INPUT_DIR)
            raise NoScriptsQueued(
                f"Created the inputs folder: {INPUT_DIR}\nPut .md scripts "
                f"there and run podcast-generator again."
            )
        inputs = sorted(glob.glob(os.path.join(INPUT_DIR, "*.md")))
        if not inputs:
            # Not an error: an empty queue is the normal steady state for a
            # scheduled/watched run, not a misconfiguration like a missing
            # directory - see NoScriptsQueued's use in main().
            raise NoScriptsQueued(f"No .md scripts found in {INPUT_DIR}.")

    jobs = []
    for input_path in inputs:
        # Honor --output only when converting a single explicitly named file.
        if args.output and args.input_path and len(inputs) == 1:
            output_path = args.output
        else:
            base = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(OUTPUT_DIR, base + "." + fmt)
        jobs.append((input_path, output_path))

    return jobs


class ScriptVoices:
    """What one script is read with: narrator, speakers, lexicon, CLI options."""

    def __init__(self, raw_text, input_path, args):
        # In a dialogue script this is the narrator's voice, for any text
        # before the first speaker label; --voice changes only that.
        self.voice = resolve_voice(raw_text, args.voice)
        self.speakers = resolve_speaker_voices(raw_text)
        self.lexicon = load_lexicon(raw_text, os.path.dirname(os.path.abspath(input_path)),
                                    cli_lexicon=args.lexicon)
        self.speed = args.speed
        self.lang_code = args.lang_code


def synthesize_turns(engine, turns, voices):
    """Speak [(speaker, text), ...] and return one audio array.

    Each turn is read in its speaker's voice (the narrator's for None),
    with a short pause between turns. The lexicon is applied here, after
    the markdown cleanup, so a phoneme override like [Kokoro](/kˈOkəɹO/)
    reaches Kokoro instead of being stripped as a link.
    """
    import numpy as np

    pause = np.zeros(int(engine.sample_rate * TURN_PAUSE_SECONDS), dtype=np.float32)
    pieces = []
    for speaker, text in turns:
        turn_voice = voices.speakers[speaker] if speaker else voices.voice
        # The accent code must match the voice; derive it from the voice's
        # first letter unless the caller pinned one with --lang.
        lang_code = voices.lang_code if voices.lang_code else turn_voice[0]
        if pieces:
            pieces.append(pause)
        pieces.append(engine.synthesize(apply_lexicon(text, voices.lexicon), turn_voice,
                                        speed=voices.speed, lang_code=lang_code))
    return pieces[0] if len(pieces) == 1 else np.concatenate(pieces)


def process_job(engine, input_path, output_path, args):
    """Convert a single script to audio. Raises on any failure."""
    with open(input_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    voices = ScriptVoices(raw_text, input_path, args)
    if voices.speakers:
        turns = split_turns(raw_text, voices.speakers)
    else:
        turns = [(None, strip_markdown(raw_text))]
    if not any(text.strip() for _, text in turns):
        raise ValueError("no spoken text found after stripping the markdown.")
    if voices.speakers:
        cast = ", ".join(f"{name}={v}" for name, v in voices.speakers.items())
        print(f"Dialogue: {cast}; {len(turns)} turns.")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    full_audio = synthesize_turns(engine, turns, voices)
    write_audio(full_audio, output_path, args.response_format, engine.sample_rate)


def synthesize_pages(engine, pages, voices):
    """Speak each planned page: [(page, audio or None, hold seconds), ...].

    A page is held for its narration plus INTER_PAGE_PAUSE_SECONDS, or for
    SILENT_HOLD_SECONDS when it has nothing to say (audio None).
    """
    results = []
    for page, turns in pages:
        if turns:
            print(f"Page {page}...")
            audio = synthesize_turns(engine, turns, voices)
            hold = len(audio) / engine.sample_rate + INTER_PAGE_PAUSE_SECONDS
        else:
            audio, hold = None, SILENT_HOLD_SECONDS
        results.append((page, audio, hold))
    return results


def _clock(seconds):
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}:{secs:02d}"


def preview_job(engine, input_path, args):
    """Synthesize a script without saving anything, and print its timing.

    A briefing script (one with `## Page N` markers) gets one row per page;
    any other script gets a single row. Raises on any failure.
    """
    with open(input_path, "r", encoding="utf-8") as f:
        raw_text = f.read()
    voices = ScriptVoices(raw_text, input_path, args)

    if has_page_markers(raw_text):
        pages, warnings = plan_pages(split_pages(raw_text, voices.speakers))
        for warning in warnings:
            print(f"Warning: {warning}")
        timed = synthesize_pages(engine, pages, voices)
        words = {page: sum(len(text.split()) for _, text in turns) for page, turns in pages}
    else:
        turns = (split_turns(raw_text, voices.speakers) if voices.speakers
                 else [(None, strip_markdown(raw_text))])
        if not any(text.strip() for _, text in turns):
            raise ValueError("no spoken text found after stripping the markdown.")
        audio = synthesize_turns(engine, turns, voices)
        timed = [("-", audio, len(audio) / engine.sample_rate)]
        words = {"-": sum(len(text.split()) for _, text in turns)}

    print(f"\n{'Page':>4}  {'Words':>5}  {'Speech':>7}  {'Shown':>7}  {'Starts':>6}")
    start = 0.0
    for page, audio, hold in timed:
        speech = f"{len(audio) / engine.sample_rate:6.1f}s" if audio is not None else "silent"
        print(f"{page:>4}  {words[page]:>5}  {speech:>7}  {hold:6.1f}s  {_clock(start):>6}")
        start += hold
    shown = f"{len(timed)} page(s), " if has_page_markers(raw_text) else ""
    print(f"Total: {shown}{_clock(start)}.")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="podcast-generator",
        description="Convert markdown podcast scripts into spoken-word audio "
                    "files using Kokoro, a free local TTS model. With no "
                    "argument, converts every .md script in the inputs "
                    "folder and writes the audio to the outputs folder.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "input_path",
        metavar="input_script.md",
        nargs="?",
        default=None,
        help="Optional path to a single markdown script. If omitted, every "
             ".md file in the inputs folder is converted.",
    )
    parser.add_argument(
        "--voice",
        choices=VOICE_CHOICES,
        default=None,
        metavar="VOICE",
        help=f"Kokoro voice for the whole run, overriding any per-script "
             f"**Voice:** line (default: the script's own voice, or "
             f"{DEFAULT_VOICE}). In a dialogue script (one with a **Voices:** "
             f"line) it changes only the narrator; speakers keep their voices. "
             f"The accent is derived from the voice's first "
             f"letter ('a' American, 'b' British) unless --lang is given.",
    )
    parser.add_argument(
        "--lang",
        dest="lang_code",
        default=None,
        help="Language/accent code ('a' American English, 'b' British "
             "English). Defaults to the first letter of the chosen voice.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=DEFAULT_SPEED,
        help=f"Speaking rate multiplier (default: {DEFAULT_SPEED}; "
             "e.g. 0.9 slower, 1.1 faster).",
    )
    parser.add_argument(
        "--format",
        dest="response_format",
        choices=FORMAT_CHOICES,
        default=DEFAULT_FORMAT,
        help=f"Audio output format (default: {DEFAULT_FORMAT}).",
    )
    parser.add_argument(
        "--lexicon",
        metavar="FILE",
        default=None,
        help="Extra pronunciation lexicon for this run (lines of "
             "'written form = spoken form'). Applied on top of lexicon.txt "
             "in the home folder and any script's **Lexicon:** file.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Single-file mode only: synthesize the script and print its "
             "timing (per page, for a briefing script with '## Page N' "
             "markers) without saving audio or archiving the script.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="If another conversion run is in progress, wait for it to "
             f"finish (up to {WAIT_FOR_RUN_MINUTES} minutes) instead of "
             "exiting.",
    )
    parser.add_argument(
        "--output",
        metavar="output_file",
        default=None,
        help="Output file path. Only used in single-file mode; ignored when "
             "converting the whole inputs folder. Defaults to "
             "<outputs folder>/<script-name>.<format>.",
    )
    return parser.parse_args(argv[1:])


def setup_logging():
    """Show voxport's progress messages (model loads, each segment) on stdout.

    voxport reports progress through logging rather than print(), so it only
    appears when the app turns it on. Call after any stdout redirect.
    """
    logging.basicConfig(stream=sys.stdout, format="%(message)s", level=logging.WARNING)
    logging.getLogger("voxport").setLevel(logging.DEBUG)


def main(argv):
    if redirect_output_if_windowless():
        print(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} ---")
    setup_logging()
    args = parse_args(argv)

    lock = acquire_run_lock()
    if lock is None and args.wait:
        print("Another conversion run is in progress; waiting for it to finish.")
        deadline = time.monotonic() + WAIT_FOR_RUN_MINUTES * 60
        while lock is None and time.monotonic() < deadline:
            time.sleep(WAIT_POLL_SECONDS)
            lock = acquire_run_lock()
    if lock is None:
        if args.input_path:
            print("Error: another conversion run is in progress; try again "
                  "when it finishes.", file=sys.stderr)
            return 1
        # Not an error: the run already going will pick up the queue.
        print("Another conversion run is already in progress; leaving the "
              "queue to it.")
        return 0
    try:
        return run(args)
    finally:
        release_run_lock(lock)


def run(args):
    if args.preview and not args.input_path:
        print("Error: --preview needs a script: podcast-generator SCRIPT.md --preview",
              file=sys.stderr)
        return 1
    if args.output and not args.input_path:
        print("Note: --output is ignored in batch mode; audio is written to "
              "the outputs folder using each script's name.", file=sys.stderr)

    # Discover jobs *before* importing voxport/torch/kokoro — an empty
    # inputs folder (the common case for a scheduled run) then exits almost
    # instantly instead of paying model-load cost for nothing.
    try:
        jobs = resolve_jobs(args)
    except NoScriptsQueued as exc:
        # Not an error - the normal steady state for a scheduled/watched
        # run. Exit 0 so Task Scheduler's history doesn't read every idle
        # check as a failure.
        print(str(exc))
        return 0
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Validate up front that any explicitly named single file actually exists.
    if args.input_path and not os.path.isfile(args.input_path):
        print(f"Error: file not found: {args.input_path}", file=sys.stderr)
        return 1

    # The run-wide lexicons apply to every script, so a broken one fails the
    # run here rather than moving each script into the failed folder.
    try:
        for path in (LEXICON_PATH, args.lexicon):
            if path and (path == args.lexicon or os.path.isfile(path)):
                read_lexicon_file(path)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        from voxport.tts.kokoro_direct import KokoroDirectTTS
        import soundfile  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        print("Error: Kokoro isn't installed. Run "
              "pip install \"voxport[kokoro]\" (see README.md, Installation).",
              file=sys.stderr)
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Found {len(jobs)} script(s) to convert in {os.path.dirname(os.path.abspath(jobs[0][0]))}.")

    # A single engine instance is reused across every script in the run;
    # KokoroDirectTTS caches its pipeline by language, so the model loads at
    # most once per accent used in the run.
    engine = KokoroDirectTTS()

    if args.preview:
        # Nothing is saved or archived, so a failure leaves the script alone.
        try:
            preview_job(engine, jobs[0][0], args)
        except Exception as exc:  # noqa: BLE001
            print(f"Error previewing {jobs[0][0]}: {exc}", file=sys.stderr)
            return 1
        return 0

    succeeded = []
    failed = []
    for input_path, output_path in jobs:
        print(f"\n=== {os.path.basename(input_path)} -> {output_path} ===")
        try:
            process_job(engine, input_path, output_path, args)
        except Exception as exc:  # noqa: BLE001 - keep going on the next script
            print(f"Error converting {input_path}: {exc}", file=sys.stderr)
            archived_to = archive_failed_script(input_path, str(exc))
            if archived_to:
                print(f"Moved failed script to: {archived_to}", file=sys.stderr)
            failed.append(input_path)
            continue
        print(f"Saved audio to: {output_path}")
        archived_to = archive_script(input_path)
        if archived_to:
            print(f"Archived script to: {archived_to}")
        succeeded.append(output_path)

    print(f"\nDone. {len(succeeded)} succeeded, {len(failed)} failed.")
    if failed:
        for path in failed:
            print(f"  Failed: {path}", file=sys.stderr)
        return 1
    return 0


def cli():
    """Entry point for the `podcast-generator` command."""
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    cli()
