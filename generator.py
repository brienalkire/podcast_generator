#!/usr/bin/env python3
"""
generator.py

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

        python generator.py
        python generator.py --voice af_heart --speed 1.1

Scheduled / "drop folder" mode:
    There's no separate watch-mode script — running the batch command above
    on a recurring schedule (e.g. Windows Task Scheduler) against a folder
    that syncs to the cloud (via Sync.com, Dropbox, etc.) *is* watch mode.
    A run that finds nothing to do exits almost immediately (jobs are
    discovered before any heavy import), so scheduling it every 10-15
    minutes costs essentially nothing when the inputs folder is empty. See
    README.md for the exact Task Scheduler setup.

Single-file mode:
    Pass a path to one script to convert just that file. The audio still
    lands in the outputs folder by default, or wherever --output points.
    Archiving still applies if the file happens to live in the inputs
    folder; a file named from elsewhere is left where it is.

        python generator.py inputs/my-script.md
        python generator.py my-script.md --format wav --output episode01.wav

Per-script voice:
    A script may choose its own voice with a metadata line anywhere in its
    header, e.g.

        **Voice:** af_heart

    Voice precedence is: a `--voice` given on the command line (applies to the
    whole run) overrides everything; otherwise a script's `**Voice:**` line is
    used; otherwise the default voice. The `--lang` accent code is derived
    automatically from the voice's first letter unless you pass `--lang`.

Folder locations:
    Default to `inputs/`, `outputs/`, `script_archive/` next to this script.
    Override with the Podcast Watch app (scripts/podcast-watch.ps1), or via a
    `.env` file (see `.env.example`) with PODCAST_INPUTS_DIR,
    PODCAST_OUTPUTS_DIR, PODCAST_ARCHIVE_DIR — e.g. pointed at a folder
    mirrored by a cloud sync client, so scripts dropped remotely get picked
    up and the finished audio syncs back out. The same folders are used
    whether this runs manually or on a schedule.

Requirements:
    - Python 3.x
    - The packages in requirements.txt, including voxport[kokoro]: see
      README.md.
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
from datetime import datetime

from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

__version__ = "0.2.1"  # keep in sync with VERSION and CHANGELOG.md

DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
DEFAULT_FORMAT = "mp3"
FORMAT_CHOICES = ["mp3", "wav"]

# Folder locations are configurable (e.g. to point at a cloud-synced
# "drop folder") via .env; all default to script-relative local folders so
# the tool works with zero configuration out of the box. The same folders
# are used for both manual CLI runs and scheduled/unattended runs.
INPUT_DIR = os.environ.get("PODCAST_INPUTS_DIR") or os.path.join(SCRIPT_DIR, "inputs")
OUTPUT_DIR = os.environ.get("PODCAST_OUTPUTS_DIR") or os.path.join(SCRIPT_DIR, "outputs")
ARCHIVE_DIR = os.environ.get("PODCAST_ARCHIVE_DIR") or os.path.join(SCRIPT_DIR, "script_archive")
FAILED_DIR = os.path.join(ARCHIVE_DIR, "failed")

# Only one conversion run at a time on this machine. Without this, a manual
# or MCP-started run overlapping a scheduled one would convert the same
# scripts twice and trip over each other's archiving. The OS releases the
# lock automatically if a run crashes, so a stale lock file is harmless.
LOCK_PATH = os.path.join(SCRIPT_DIR, ".generator.lock")

# Where output goes when there's no console (pythonw.exe, which the
# scheduled task uses so no window flashes up), and for MCP-started runs.
LOG_PATH = os.path.join(SCRIPT_DIR, "generator.log")
OLD_LOG_PATH = os.path.join(SCRIPT_DIR, "generator.old.log")
LOG_MAX_BYTES = 1_000_000


def acquire_run_lock():
    """Return an open handle holding the run lock, or None if it's taken."""
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


def strip_markdown(raw_text):
    """Strip markdown formatting, metadata, and section labels from the script.

    Returns clean prose suitable for text-to-speech: only the words that
    should actually be spoken aloud.
    """
    lines = raw_text.splitlines()
    cleaned_lines = []

    # A metadata line looks like:  **Author:** Brien Alkire
    metadata_pattern = re.compile(r"^\s*\*\*[^*]+:\*\*")
    # A horizontal rule:  ---  or  ***  or  ___  (3 or more)
    hrule_pattern = re.compile(r"^\s*([-*_])\1{2,}\s*$")
    # A line that is entirely italic, e.g.  *End of script.*  (production note)
    italic_only_pattern = re.compile(r"^\s*\*[^*]+\*\s*$")
    seen_prose = False

    for line in lines:
        stripped = line.strip()

        # Drop blank lines for now; paragraph breaks are reconstructed later.
        if not stripped:
            cleaned_lines.append("")
            continue

        # An all-italic line is a production note. After the prose starts it
        # is the end-of-script marker, so trailing notes/appendices are not
        # spoken; before that it's front matter like *Source: ...* and is
        # just skipped (otherwise the whole script would come out empty).
        if italic_only_pattern.match(stripped):
            if seen_prose:
                break
            continue

        # Drop markdown headers (#, ##, ###, ...). In these scripts the
        # section labels (OPENING, PART ONE, CLOSING, etc.) are headers,
        # so this also removes the spoken-aloud section labels.
        if stripped.startswith("#"):
            continue

        # Drop horizontal rules.
        if hrule_pattern.match(stripped):
            continue

        # Drop metadata key/value lines (Author, Date, Version, Voice, etc.).
        if metadata_pattern.match(stripped):
            continue

        cleaned_lines.append(line)
        seen_prose = True

    text = "\n".join(cleaned_lines)

    # Strip inline markdown formatting from the remaining prose.
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
            raise FileNotFoundError(
                f"No input file given and the inputs directory does not exist: "
                f"{INPUT_DIR}\nCreate it and add one or more .md scripts, or "
                f"pass a script path directly."
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


def process_job(engine, input_path, output_path, args):
    """Convert a single script to audio. Raises on any failure."""
    with open(input_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    voice = resolve_voice(raw_text, args.voice)
    # The accent code must match the voice; derive it from the voice's first
    # letter unless the caller pinned one with --lang.
    lang_code = args.lang_code if args.lang_code else voice[0]

    cleaned = strip_markdown(raw_text)
    if not cleaned.strip():
        raise ValueError("no spoken text found after stripping the markdown.")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    full_audio = engine.synthesize(cleaned, voice, speed=args.speed, lang_code=lang_code)
    write_audio(full_audio, output_path, args.response_format, engine.sample_rate)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="generator.py",
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
             f"{DEFAULT_VOICE}). The accent is derived from the voice's first "
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

    try:
        from voxport.tts.kokoro_direct import KokoroDirectTTS
        import soundfile  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        print("Error: required packages are not installed. Run "
              "pip install -r requirements.txt — see README.md Installation.",
              file=sys.stderr)
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Found {len(jobs)} script(s) to convert.")

    # A single engine instance is reused across every script in the run;
    # KokoroDirectTTS caches its pipeline by language, so the model loads at
    # most once per accent used in the run.
    engine = KokoroDirectTTS()

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


if __name__ == "__main__":
    sys.exit(main(sys.argv))
