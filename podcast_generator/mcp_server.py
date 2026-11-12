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

import asyncio
import glob
import json
import os
import re
import shutil
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
# podcast_status(wait_seconds=...): the longest it waits in one call, kept
# under the ~60 s an MCP client typically allows a tool call, and how often
# it re-checks while waiting.
MAX_WAIT_SECONDS = 50
STATUS_POLL_SECONDS = 2

# The converter process generate_now last started. It takes the run lock
# only after Python starts up, so for its first second or two the lock alone
# would miss it.
_started_run: subprocess.Popen | None = None

mcp = MCPServer(
    "podcast-generator",
    version=g.__version__,
    instructions=(
        "Turns markdown podcast scripts into spoken audio locally with Kokoro. "
        "Typical flow: write the script, call queue_podcast, then call "
        "generate_now, then call podcast_status with "
        "wait_seconds=50, repeating while it reports 'converting', until it "
        "reports 'done' or 'failed'. podcast_status does the waiting itself, "
        "so no separate wait or sleep is needed. Conversion takes roughly a "
        "tenth of the audio's length, plus about a minute for the first one. "
        "Script rules: '#' headers, '**Key:** value' lines, '---' rules and "
        "italic-only lines are not spoken; an italic-only line after the prose "
        "starts ends the script. For a conversation between two or more "
        "speakers, start each line with the speaker's name and a colon "
        "('Maya: ...') and pass queue_podcast a voices mapping, e.g. "
        "{'Maya': 'af_heart', 'Theo': 'bm_george'}. Pronunciation fixes for "
        "acronyms and names go in the user's lexicon.txt in the home folder "
        "(lines of 'written form = spoken form'), applied to every script. "
        "Narrated briefings: given a PDF, it makes an MP4 showing each page "
        "while its narration is read. Ask the user for the PDF's full path on "
        "this computer (the server can't see chat attachments), call "
        "inspect_briefing on it for the page count and each page's text, write "
        "one section per page starting with a line '## Page N' (N as numbered "
        "in the PDF), then queue_podcast with pdf=<path>. Narrate the page; "
        "don't read the slide out word for word. Checks are strict: every "
        "marker must be a real page, in order, with no text before the first."
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
    return _set_meta_line(script, g.voice_meta_pattern, f"**Voice:** {voice}")


def _set_voices_line(script: str, voices: dict[str, str]) -> str:
    """Set the script's **Voices:** line (dialogue speakers), replacing any existing one."""
    cast = ", ".join(f"{name}={voice}" if voice else name for name, voice in voices.items())
    return _set_meta_line(script, g.voices_meta_pattern, f"**Voices:** {cast}")


def _set_meta_line(script: str, pattern: re.Pattern, new_line: str) -> str:
    """Replace the first line matching `pattern`, or insert `new_line` near the top."""
    lines = script.splitlines()
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            return "\n".join(lines) + "\n"
    # Insert after a leading '# Title' line if there is one, else at the top.
    insert_at = 0
    for i, line in enumerate(lines):
        if line.strip():
            if line.lstrip().startswith("# "):
                insert_at = i + 1
            break
    lines[insert_at:insert_at] = ["", new_line, ""]
    return "\n".join(lines).lstrip("\n") + "\n"


OUTPUT_FORMATS = [*g.FORMAT_CHOICES, "mp4"]


def _output_files(name: str) -> list[str]:
    files = [os.path.join(g.OUTPUT_DIR, f"{name}.{fmt}") for fmt in OUTPUT_FORMATS]
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


def _output_info(path: str) -> dict:
    info = {"path": path, "size_mb": round(os.path.getsize(path) / 1e6, 2),
            "finished": _when(path)}
    try:
        if path.endswith(".mp4"):
            srt_path, json_path = g.briefing_outputs(path)
            info["kind"] = "video"
            if os.path.isfile(srt_path):
                info["subtitles"] = srt_path
            with open(json_path, encoding="utf-8") as f:
                info["duration_minutes"] = round(json.load(f)["total_seconds"] / 60, 1)
        else:
            import soundfile
            info["kind"] = "audio"
            info["duration_minutes"] = round(soundfile.info(path).duration / 60, 1)
    except Exception:  # noqa: BLE001 - duration is a nice-to-have
        pass
    return info


def _briefing_module():
    try:
        from . import briefing
        briefing._pdfium()
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    return briefing


def _check_pdf_path(pdf: str) -> str:
    """An existing .pdf file's absolute path, or a ToolError."""
    path = os.path.abspath(os.path.expanduser(pdf.strip().strip('"')))
    if not path.lower().endswith(".pdf"):
        raise ToolError(f"not a .pdf file: {path}")
    if not os.path.isfile(path):
        raise ToolError(f"PDF not found: {path}. Ask the user for the full path "
                        "of the file on this computer.")
    return path


def _check_briefing(script: str, pdf_path: str) -> dict:
    """Check a briefing script against its PDF without making audio.

    Returns pages, shown pages, warnings and an estimated length. Raises
    ToolError listing what stops it.
    """
    briefing = _briefing_module()
    try:
        count = briefing.page_count(pdf_path)
        speakers = g.resolve_speaker_voices(script)
        pages, warnings = g.plan_pages(g.split_pages(script, speakers), count)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    seconds = sum(
        sum(len(text.split()) for _, text in turns) / WORDS_PER_MINUTE * 60
        + g.INTER_PAGE_PAUSE_SECONDS if turns else g.SILENT_HOLD_SECONDS
        for _, turns in pages)
    return {"pdf_pages": count, "pages_shown": [n for n, _ in pages],
            "warnings": warnings, "estimated_minutes": round(seconds / 60, 1)}


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


NEXT_STEP = ("Call generate_now to convert it, then podcast_status with "
             "wait_seconds=50 to follow it.")


def _queued_scripts(folder: str) -> list[str]:
    return sorted(os.path.basename(p)
                  for p in glob.glob(os.path.join(glob.escape(folder), "*.md")))


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
                  voices: dict[str, str] | None = None,
                  replace: bool = False, pdf: str | None = None) -> dict:
    """Save a markdown podcast script to the queue, ready to convert.

    Args:
        name: File name without extension, e.g. "myseries-ep01-introduction".
            The audio will be <name>.mp3 in the outputs folder (<name>.mp4
            for a briefing).
        script: The full markdown script. Plain paragraphs are spoken;
            '#' headers, '**Key:** value' lines, bold-only labels like
            '**INTRO**', '---' rules and italic-only lines are not. An
            italic-only line after the prose starts ends the script, so never
            wrap a mid-script sentence entirely in *...*. For a conversation,
            start each speaker's line with their name and a colon
            ("Maya: Welcome back.") and pass `voices`.
        voice: Optional Kokoro voice (see list_voices). Sets the script's
            **Voice:** line. Default af_heart. In a dialogue it's only used
            for text before the first speaker label.
        voices: For a script with two or more speakers: each speaker's name
            and Kokoro voice, e.g. {"Maya": "af_heart", "Theo": "bm_george"}.
            Sets the script's **Voices:** line. An empty voice ("") picks a
            distinct one automatically.
        replace: Overwrite a queued script or finished audio with this name.
        pdf: For a narrated briefing (an MP4 of the PDF's pages): the PDF's
            full path on this computer. The script then needs a '## Page N'
            line before each page's narration (see inspect_briefing). The
            PDF is copied into the queue, and checked against the script
            before anything is queued. Sets the script's **Briefing:** line.
    """
    name = _check_name(name)
    # A briefing's PDF: the pdf argument, or an absolute path in a
    # **Briefing:** line the script already has.
    pdf_path = pdf or g.briefing_pdf_path(script, os.path.join(g.CONNECTOR_QUEUE_DIR, name + ".md"))
    briefing_check = None
    if pdf_path:
        pdf_path = _check_pdf_path(pdf_path)
        briefing_check = _check_briefing(script, pdf_path)
        try:
            _briefing_module().check_ffmpeg()
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc
        # The queued script names the queued copy of the PDF, next to it.
        script = _set_meta_line(script, g.briefing_meta_pattern, f"**Briefing:** {name}.pdf")
    if voice:
        if voice not in g.VOICE_CHOICES:
            raise ToolError(f"unknown voice '{voice}'. Call list_voices for the options.")
        script = _set_voice_line(script, voice)
    if voices:
        for speaker, speaker_voice in voices.items():
            if speaker_voice and speaker_voice not in g.VOICE_CHOICES:
                raise ToolError(f"unknown voice '{speaker_voice}' for {speaker}. "
                                "Call list_voices for the options.")
        script = _set_voices_line(script, voices)
    try:
        chosen_voice = g.resolve_voice(script, None)
        speakers = g.resolve_speaker_voices(script)
        spoken = g.spoken_text(script)
        # The script will be converted from the queue folder, so a relative
        # **Lexicon:** path resolves there.
        g.load_lexicon(script, g.CONNECTOR_QUEUE_DIR)
    except ValueError as exc:  # an unknown voice, a malformed **Voices:** line, or a bad lexicon
        raise ToolError(str(exc)) from exc

    words = len(spoken.split())
    if not words:
        raise ToolError(
            "nothing would be spoken: after removing headers, metadata and "
            "italic-only lines, the script is empty. Check for an italic-only "
            "line before the prose that ends the script early.")

    target = os.path.join(g.CONNECTOR_QUEUE_DIR, name + ".md")
    # A script of the same name in the watch's inputs folder would write the
    # same audio file, so it's refused even with replace=true: that script
    # is the user's, not the connector's to overwrite.
    if os.path.exists(os.path.join(g.INPUT_DIR, name + ".md")):
        raise ToolError(
            f"a script named '{name}' is waiting in the folder watch's inputs "
            f"folder ({g.INPUT_DIR}), and both would write the same audio file. "
            "Pick another name.")
    if not replace:
        if os.path.exists(target):
            raise ToolError(f"'{name}' is already queued. Pass replace=true to overwrite it.")
        existing = _output_files(name)
        if existing:
            raise ToolError(
                f"audio for '{name}' already exists ({existing[0]}). Pick another "
                "name, or pass replace=true to regenerate it.")

    os.makedirs(g.CONNECTOR_QUEUE_DIR, exist_ok=True)
    queued_pdf = os.path.join(g.CONNECTOR_QUEUE_DIR, name + ".pdf")
    if not pdf_path and os.path.isfile(queued_pdf):
        os.remove(queued_pdf)  # left by an earlier briefing of this name
    if pdf_path:
        # A copy, so a later edit or move of the original can't change the
        # queued job. Written before the script, which is what starts a job.
        if os.path.normcase(pdf_path) != os.path.normcase(queued_pdf):
            shutil.copyfile(pdf_path, queued_pdf + ".part")
            os.replace(queued_pdf + ".part", queued_pdf)
    partial = target + ".part"  # not *.md, so a run can't pick it up half-written
    with open(partial, "w", encoding="utf-8", newline="\n") as f:
        f.write(script)
    os.replace(partial, target)

    result = {"queued": target, "voice": chosen_voice}
    if speakers:
        result["speakers"] = speakers
        heard = {speaker for speaker, _ in g.split_turns(script, speakers)}
        unheard = [n for n in speakers if n not in heard]
        if unheard:
            result["warning"] = (
                f"no lines start with {', '.join(n + ':' for n in unheard)}, so "
                "they are never heard. Check the line labels match the speaker names.")
    estimate = round(words / WORDS_PER_MINUTE, 1)
    if briefing_check:
        result["briefing"] = {"pdf": pdf_path, "pdf_pages": briefing_check["pdf_pages"],
                              "pages_shown": briefing_check["pages_shown"]}
        if briefing_check["warnings"]:
            result["warnings"] = briefing_check["warnings"]
        estimate = briefing_check["estimated_minutes"]
    return {
        **result,
        "spoken_words": words,
        "estimated_minutes": estimate,
        "next_step": NEXT_STEP,
    }


@mcp.tool()
def inspect_briefing(pdf: str, max_chars_per_page: int = 600) -> dict:
    """Read a PDF before writing a narrated briefing for it.

    Returns the page count and each page's text (and a title: its first
    line), so the narration can follow the pages and use the right
    '## Page N' numbers. Pages with no text layer (scanned images) are
    flagged; ask the user what those pages show. Also returns a
    script_skeleton with one marker per page to fill in.

    Args:
        pdf: The PDF's full path on this computer.
        max_chars_per_page: Truncate each page's text to this many characters.
    """
    path = _check_pdf_path(pdf)
    briefing = _briefing_module()
    try:
        texts = briefing.page_texts(path)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    limit = max(50, min(int(max_chars_per_page), 5000))
    pages = []
    for number, text in enumerate(texts, start=1):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        page = {"page": number, "title": lines[0][:120] if lines else "",
                "text": " ".join(lines)[:limit]}
        if not lines:
            page["no_text_layer"] = True
        pages.append(page)
    result = {"pdf": path, "pages": len(texts), "page_text": pages,
              "script_skeleton": "\n\n".join(f"## Page {n}\n\n" for n in range(1, len(texts) + 1))}
    blank = [p["page"] for p in pages if p.get("no_text_layer")]
    if blank:
        result["warning"] = (f"pages {', '.join(map(str, blank))} have no text layer "
                             "(scanned images, or pictures only); ask the user what they show.")
    return result


@mcp.tool()
def validate_briefing(script: str, pdf: str | None = None) -> dict:
    """Check a briefing script against its PDF without queueing or making audio.

    Reports what queue_podcast would refuse (missing or mistyped '## Page N'
    markers, pages the PDF doesn't have, pages out of order or repeated,
    text before the first marker) and warnings (pages with no narration,
    which are shown silently; very long sections).

    Args:
        script: The full markdown briefing script.
        pdf: The PDF's full path on this computer. Optional if the script
            has a **Briefing:** line with a full path.
    """
    pdf_path = pdf or g.briefing_pdf_path(script, os.path.join(g.CONNECTOR_QUEUE_DIR, "x.md"))
    if not pdf_path:
        raise ToolError("no PDF given: pass pdf=<the PDF's full path>.")
    pdf_path = _check_pdf_path(pdf_path)
    try:
        check = _check_briefing(script, pdf_path)
    except ToolError as exc:
        return {"ok": False, "errors": str(exc), "pdf": pdf_path}
    return {"ok": True, "pdf": pdf_path, **check}


@mcp.tool()
def generate_now() -> dict:
    """Start converting every script queue_podcast has queued, in the background.

    Returns immediately. Use podcast_status (with wait_seconds to wait for
    it) to see when each one is done. Only the connector's own queue is
    converted, never scripts in the folder watch's inputs folder. If another
    conversion is running (the watch, or an earlier generate_now), this one
    waits for it to finish and then starts.
    """
    queued = _queued_scripts(g.CONNECTOR_QUEUE_DIR)
    global _started_run
    if not queued:
        return {"started": False, "reason": "Nothing is queued.", "queued": []}
    busy = _converting()

    log = g.open_log()
    log.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} (started from MCP) ---\n")
    log.flush()
    _started_run = subprocess.Popen(
        [sys.executable, "-m", "podcast_generator", "--wait"],
        cwd=g.HOME_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        creationflags=NO_WINDOW,
        env={**os.environ, "PODCAST_INPUTS_DIR": g.CONNECTOR_QUEUE_DIR},
    )
    log.close()
    note = "The first script includes about a minute of model loading."
    if busy:
        note = ("Another conversion is running; this one starts when it "
                "finishes. " + note)
    return {"started": True, "queued": queued, "note": note}


def _status_once(name: str) -> dict:
    """podcast_status's answer right now, without waiting."""
    running = _converting()
    queued_path = os.path.join(g.CONNECTOR_QUEUE_DIR, name + ".md")
    if os.path.isfile(queued_path):
        if running:
            return {"status": "converting",
                    "detail": "A conversion run is in progress, or waiting for "
                    "another to finish, and this script is in its queue."}
        return {"status": "queued", "next_step": NEXT_STEP}

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
        return {"status": "done", **_output_info(newest_output)}
    return {"status": "not found",
            "detail": f"No queued script, audio, or failure note named '{name}'."}


def _may_still_change(status: dict) -> bool:
    """Whether waiting could change this status. Only a conversion moves it;
    a queued script waits for generate_now."""
    return status["status"] == "converting"


@mcp.tool()
async def podcast_status(name: str, wait_seconds: int = 0) -> dict:
    """Report whether a podcast is queued, converting, done, or failed.

    Args:
        name: The name given to queue_podcast (without extension).
        wait_seconds: Wait up to this many seconds (max 50) for a queued or
            converting podcast to finish before answering, instead of
            answering at once. Use this to follow a conversion: call again
            with wait_seconds=50 while the status is still "converting".
            Returns early as soon as the status is final, or if waiting
            can't change it (queued but not started: call generate_now).
    """
    name = _check_name(name)
    wait_seconds = max(0, min(int(wait_seconds), MAX_WAIT_SECONDS))
    loop = asyncio.get_running_loop()
    start = loop.time()
    while True:
        # Off the event loop: the watch check runs PowerShell.
        status = await asyncio.to_thread(_status_once, name)
        waited = loop.time() - start
        remaining = wait_seconds - waited
        if remaining <= 0 or not _may_still_change(status):
            break
        await asyncio.sleep(min(STATUS_POLL_SECONDS, remaining))
    if wait_seconds:
        status["waited_seconds"] = round(waited)
    return status


@mcp.tool()
def list_podcasts(limit: int = 20) -> dict:
    """Overview: version, folders, queued scripts, recent audio, briefings and failures.

    "queued" is the connector's own queue. "watch_inputs" lists scripts in
    the folder watch's inputs folder, which the connector never converts.

    Args:
        limit: Maximum number of recent audio files and failures to list.
    """
    limit = max(1, min(limit, 200))

    def newest(paths):
        return sorted(paths, key=os.path.getmtime, reverse=True)[:limit]

    audio = newest(p for fmt in g.FORMAT_CHOICES
                   for p in glob.glob(os.path.join(g.OUTPUT_DIR, f"*.{fmt}")))
    videos = newest(glob.glob(os.path.join(g.OUTPUT_DIR, "*.mp4")))
    failures = newest(glob.glob(os.path.join(g.FAILED_DIR, "*.error.txt")))
    return {
        "version": g.__version__,
        "folders": {"connector_queue": g.CONNECTOR_QUEUE_DIR, "outputs": g.OUTPUT_DIR,
                    "archive": g.ARCHIVE_DIR, "watch_inputs": g.INPUT_DIR},
        "watch": _watch_state(),
        "converting_now": _converting(),
        "queued": _queued_scripts(g.CONNECTOR_QUEUE_DIR),
        "watch_inputs": _queued_scripts(g.INPUT_DIR),
        "recent_audio": [{"name": os.path.basename(p), "path": p, "finished": _when(p)}
                         for p in audio],
        "recent_briefings": [{"name": os.path.basename(p), "path": p, "finished": _when(p)}
                             for p in videos],
        "recent_failures": [{"script": os.path.basename(p)[: -len(".error.txt")],
                             "failed_at": _when(p),
                             "error": _read(p, 300)} for p in failures],
    }


@mcp.tool()
def set_watch(on: bool) -> dict:
    """Turn the scheduled folder watch on or off (Windows only).

    The watch converts scripts dropped in the inputs folder every few
    minutes. It doesn't affect scripts queued with queue_podcast, which
    always need generate_now.
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
