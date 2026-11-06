"""
podcast_generator.mcp_server: the `podcast-generator-mcp` command.

An MCP (Model Context Protocol) server that lets an AI app such as Claude
Desktop make podcasts with podcast_generator: queue a script, start a
conversion, check on it, and turn the folder watch on or off.

It runs locally over stdio and uses the same folders and settings (.env) as
the `podcast-generator` command and the Podcast Watch app. Conversion itself
always happens in a separate `python -m podcast_generator` process, never
inside a tool call, because a long script takes minutes to synthesize.

Needs the `mcp` extra: pip install "podcast-generator[mcp]". Run by an MCP
client, not by hand. `podcast-generator-mcp --config` prints the
claude_desktop_config.json entry for this install, with the command's full
path (Claude Desktop doesn't see a virtual environment's PATH).

Never print to stdout here: stdout carries the MCP protocol.
"""

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError as exc:
    raise SystemExit(
        "podcast-generator-mcp needs the MCP SDK: "
        'pip install "podcast-generator[mcp]"'
    ) from exc

from . import generator as g

WATCH_TASK = "PodcastGeneratorWatch"
WORDS_PER_MINUTE = 175  # Kokoro's pace at speed 1.0
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,99}$")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# The converter process generate_now last started. It takes the run lock
# only after Python starts up, so for its first second or two the lock alone
# would miss it.
_started_run: subprocess.Popen | None = None

mcp = MCPServer(
    "podcast-generator",
    version=g.__version__,
    instructions=(
        "Turns markdown podcast scripts into spoken audio locally with Kokoro. "
        "Typical flow: write the script, call queue_podcast, then (unless the "
        "folder watch is on) call generate_now, then poll podcast_status until "
        "it reports 'done'. Conversion takes roughly a tenth of the audio's "
        "length or more, so check back rather than waiting in one call. "
        "Script rules: '#' headers, '**Key:** value' lines, '---' rules and "
        "italic-only lines are not spoken; an italic-only line after the prose "
        "starts ends the script."
    ),
)


# ------------------------------------------------------------- helpers

def _check_name(name: str) -> str:
    name = name.strip()
    if name.lower().endswith(".md"):
        name = name[:-3]
    if not NAME_PATTERN.match(name) or ".." in name:
        raise ToolError(
            "name must be 1-100 characters of letters, digits, spaces, '.', "
            "'_' or '-', e.g. 'myseries-ep01-introduction'."
        )
    return name


def _set_voice_line(script: str, voice: str) -> str:
    """Set the script's **Voice:** line, replacing any existing one."""
    lines = script.splitlines()
    for i, line in enumerate(lines):
        if g.voice_meta_pattern.match(line):
            lines[i] = f"**Voice:** {voice}"
            return "\n".join(lines) + "\n"
    # Insert after a leading '# Title' line if there is one, else at the top.
    insert_at = 0
    for i, line in enumerate(lines):
        if line.strip():
            if line.lstrip().startswith("# "):
                insert_at = i + 1
            break
    lines[insert_at:insert_at] = ["", f"**Voice:** {voice}", ""]
    return "\n".join(lines).lstrip("\n") + "\n"


def _output_files(name: str) -> list[str]:
    files = [os.path.join(g.OUTPUT_DIR, f"{name}.{fmt}") for fmt in g.FORMAT_CHOICES]
    return [f for f in files if os.path.isfile(f)]


def _failure_notes(name: str) -> list[str]:
    """.error.txt notes for this name, newest first."""
    pattern = os.path.join(glob.escape(g.FAILED_DIR), glob.escape(name) + "*.md.error.txt")
    notes = [p for p in glob.glob(pattern)
             if re.fullmatch(re.escape(name) + r"(_\d{8}_\d{6})?\.md\.error\.txt",
                             os.path.basename(p))]
    return sorted(notes, key=os.path.getmtime, reverse=True)


def _converting() -> bool:
    if _started_run is not None and _started_run.poll() is None:
        return True
    return g.is_run_in_progress()


def _when(path: str) -> str:
    return datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")


def _audio_info(path: str) -> dict:
    info = {"path": path, "size_mb": round(os.path.getsize(path) / 1e6, 2),
            "finished": _when(path)}
    try:
        import soundfile
        info["duration_minutes"] = round(soundfile.info(path).duration / 60, 1)
    except Exception:  # noqa: BLE001 - duration is a nice-to-have
        pass
    return info


def _read(path: str, limit: int = 2000) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read(limit).strip()


def _powershell(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW,
    )


def _watch_state() -> str:
    """'on', 'off', 'not set up', or 'unavailable' (not Windows / error)."""
    if os.name != "nt":
        return "unavailable"
    try:
        result = _powershell(
            f"(Get-ScheduledTask -TaskName '{WATCH_TASK}' -ErrorAction Stop).State")
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    state = result.stdout.strip()
    if result.returncode != 0 or not state:
        return "not set up"
    return "off" if state == "Disabled" else "on"


def _watch_interval_minutes() -> int | None:
    try:
        result = _powershell(
            f"(Get-ScheduledTask -TaskName '{WATCH_TASK}').Triggers | "
            "ForEach-Object { $_.Repetition.Interval } | Select-Object -First 1")
        match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", result.stdout.strip())
        if match:
            return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _next_step_hint(watch: str) -> str:
    if watch == "on":
        minutes = _watch_interval_minutes()
        every = f"every {minutes} minutes" if minutes else "regularly"
        return (f"The folder watch is on (checks {every}), so it will be "
                "converted automatically. Use podcast_status to follow it.")
    return ("The folder watch is not on. Call generate_now to convert it, "
            "then podcast_status to follow it.")


# --------------------------------------------------------------- tools

@mcp.tool()
def list_voices() -> dict:
    """List the Kokoro voices scripts can use, grouped by accent and gender.

    Voice names start with accent (a = American, b = British) and gender
    (m = male, f = female).
    """
    groups = {"american_male": "am_", "american_female": "af_",
              "british_male": "bm_", "british_female": "bf_"}
    return {
        "default": g.DEFAULT_VOICE,
        **{group: [v for v in g.VOICE_CHOICES if v.startswith(prefix)]
           for group, prefix in groups.items()},
    }


@mcp.tool()
def queue_podcast(name: str, script: str, voice: str | None = None,
                  replace: bool = False) -> dict:
    """Save a markdown podcast script to the inputs folder, ready to convert.

    Args:
        name: File name without extension, e.g. "myseries-ep01-introduction".
            The audio will be <name>.mp3 in the outputs folder.
        script: The full markdown script. Plain paragraphs are spoken;
            '#' headers, '**Key:** value' lines, '---' rules and italic-only
            lines are not. An italic-only line after the prose starts ends
            the script, so never wrap a mid-script sentence entirely in *...*.
        voice: Optional Kokoro voice (see list_voices). Sets the script's
            **Voice:** line. Default af_heart.
        replace: Overwrite a queued script or finished audio with this name.
    """
    name = _check_name(name)
    if voice:
        if voice not in g.VOICE_CHOICES:
            raise ToolError(f"unknown voice '{voice}'. Call list_voices for the options.")
        script = _set_voice_line(script, voice)
    try:
        chosen_voice = g.resolve_voice(script, None)
    except ValueError as exc:  # an unknown **Voice:** line
        raise ToolError(str(exc)) from exc

    spoken = g.strip_markdown(script)
    words = len(spoken.split())
    if not words:
        raise ToolError(
            "nothing would be spoken: after removing headers, metadata and "
            "italic-only lines, the script is empty. Check for an italic-only "
            "line before the prose that ends the script early.")

    target = os.path.join(g.INPUT_DIR, name + ".md")
    if not replace:
        if os.path.exists(target):
            raise ToolError(f"'{name}' is already queued. Pass replace=true to overwrite it.")
        existing = _output_files(name)
        if existing:
            raise ToolError(
                f"audio for '{name}' already exists ({existing[0]}). Pick another "
                "name, or pass replace=true to regenerate it.")

    os.makedirs(g.INPUT_DIR, exist_ok=True)
    partial = target + ".part"  # not *.md, so a run can't pick it up half-written
    with open(partial, "w", encoding="utf-8", newline="\n") as f:
        f.write(script)
    os.replace(partial, target)

    watch = _watch_state()
    return {
        "queued": target,
        "voice": chosen_voice,
        "spoken_words": words,
        "estimated_minutes": round(words / WORDS_PER_MINUTE, 1),
        "watch": watch,
        "next_step": _next_step_hint(watch),
    }


@mcp.tool()
def generate_now() -> dict:
    """Start converting every queued script in the background.

    Returns immediately. Use podcast_status to see when each one is done.
    Does nothing if a conversion is already running (it will take the
    whole queue).
    """
    queued = sorted(os.path.basename(p) for p in glob.glob(os.path.join(g.INPUT_DIR, "*.md")))
    global _started_run
    if _converting():
        return {"started": False, "reason": "A conversion is already running; it "
                "will convert the queued scripts.", "queued": queued}
    if not queued:
        return {"started": False, "reason": "Nothing is queued.", "queued": []}

    log = g.open_log()
    log.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} (started from MCP) ---\n")
    log.flush()
    _started_run = subprocess.Popen(
        [sys.executable, "-m", "podcast_generator"],
        cwd=g.HOME_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        creationflags=NO_WINDOW,
    )
    log.close()
    return {"started": True, "queued": queued,
            "note": "The first script includes about a minute of model loading."}


@mcp.tool()
def podcast_status(name: str) -> dict:
    """Report whether a podcast is queued, converting, done, or failed.

    Args:
        name: The name given to queue_podcast (without extension).
    """
    name = _check_name(name)
    running = _converting()
    queued_path = os.path.join(g.INPUT_DIR, name + ".md")
    if os.path.isfile(queued_path):
        if running:
            return {"status": "converting",
                    "detail": "A conversion run is in progress and this script is in its queue."}
        watch = _watch_state()
        return {"status": "queued", "watch": watch, "next_step": _next_step_hint(watch)}

    outputs = _output_files(name)
    notes = _failure_notes(name)
    newest_output = max(outputs, key=os.path.getmtime) if outputs else None
    newest_note = notes[0] if notes else None

    if newest_note and (not newest_output
                        or os.path.getmtime(newest_note) > os.path.getmtime(newest_output)):
        return {"status": "failed", "failed_at": _when(newest_note),
                "error": _read(newest_note),
                "script": newest_note[: -len(".error.txt")],
                "next_step": "Fix the script and queue it again with replace=true."}
    if newest_output:
        return {"status": "done", **_audio_info(newest_output)}
    return {"status": "not found",
            "detail": f"No queued script, audio, or failure note named '{name}'."}


@mcp.tool()
def list_podcasts(limit: int = 20) -> dict:
    """Overview: folders, watch state, queued scripts, recent audio and failures.

    Args:
        limit: Maximum number of recent audio files and failures to list.
    """
    limit = max(1, min(limit, 200))

    def newest(paths):
        return sorted(paths, key=os.path.getmtime, reverse=True)[:limit]

    audio = newest(p for fmt in g.FORMAT_CHOICES
                   for p in glob.glob(os.path.join(g.OUTPUT_DIR, f"*.{fmt}")))
    failures = newest(glob.glob(os.path.join(g.FAILED_DIR, "*.error.txt")))
    return {
        "folders": {"inputs": g.INPUT_DIR, "outputs": g.OUTPUT_DIR, "archive": g.ARCHIVE_DIR},
        "watch": _watch_state(),
        "converting_now": _converting(),
        "queued": sorted(os.path.basename(p)
                         for p in glob.glob(os.path.join(g.INPUT_DIR, "*.md"))),
        "recent_audio": [{"name": os.path.basename(p), "path": p, "finished": _when(p)}
                         for p in audio],
        "recent_failures": [{"script": os.path.basename(p)[: -len(".error.txt")],
                             "failed_at": _when(p),
                             "error": _read(p, 300)} for p in failures],
    }


@mcp.tool()
def set_watch(on: bool) -> dict:
    """Turn the scheduled folder watch on or off (Windows only).

    While on, queued scripts are converted automatically every few minutes.
    """
    state = _watch_state()
    if state in ("not set up", "unavailable"):
        return {"watch": state, "changed": False,
                "detail": "The watch task isn't set up on this machine. Use the "
                "Podcast Watch app's 'Set up watch' button, or call generate_now instead."}
    cmdlet = "Enable-ScheduledTask" if on else "Disable-ScheduledTask"
    result = _powershell(f"{cmdlet} -TaskName '{WATCH_TASK}' -ErrorAction Stop | Out-Null")
    if result.returncode != 0:
        raise ToolError(f"Windows refused to change the watch: {result.stderr.strip()}")
    return {"watch": _watch_state(), "changed": True}


def desktop_config(argv0: str | None = None) -> dict:
    """The claude_desktop_config.json snippet that starts this install.

    Uses the full path of the running command, since Claude Desktop doesn't
    see a virtual environment's PATH, and passes PODCAST_GENERATOR_HOME
    through if it's set, since Claude Desktop doesn't see the shell's
    environment either.
    """
    argv0 = os.path.abspath(argv0 or sys.argv[0])
    if argv0.lower().endswith(".py"):  # python -m podcast_generator.mcp_server
        entry = {"command": sys.executable,
                 "args": ["-m", "podcast_generator.mcp_server"]}
    else:
        if os.name == "nt" and not argv0.lower().endswith(".exe") \
                and os.path.isfile(argv0 + ".exe"):
            argv0 += ".exe"
        entry = {"command": argv0}
    home = os.environ.get("PODCAST_GENERATOR_HOME")
    if home:
        entry["env"] = {"PODCAST_GENERATOR_HOME": os.path.abspath(home)}
    return {"mcpServers": {"podcast-generator": entry}}


USAGE = """\
usage: podcast-generator-mcp            run the MCP server (an MCP client starts this)
       podcast-generator-mcp --config   print the Claude Desktop config for this install
       podcast-generator-mcp --version"""


def main():
    """Entry point for the `podcast-generator-mcp` command."""
    args = sys.argv[1:]
    if args == ["--config"]:
        print(json.dumps(desktop_config(), indent=2))
        return 0
    if args == ["--version"]:
        print(f"podcast-generator-mcp {g.__version__}")
        return 0
    if args:
        print(USAGE, file=sys.stderr)
        return 2
    mcp.run()


if __name__ == "__main__":
    main()
