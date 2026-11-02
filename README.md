# podcast_generator

Converts markdown podcast scripts into spoken-word audio files, using
[`voxport`](https://github.com/brienalkire/voxport)'s `KokoroDirectTTS` for local, offline-capable
text-to-speech. No API key required.

This README is a quick start. See [MANUAL.md](MANUAL.md) for the full
guide: script-writing conventions, complete CLI reference, the voice
catalog, and troubleshooting.

## Installation

Requires Python 3.10+ and Windows for the scheduled mode below (the CLI
itself is plain Python).

```
git clone https://github.com/brienalkire/podcast_generator.git
cd podcast_generator
python -m venv .venv
.venv\Scripts\activate          # Windows (bash: source .venv/Scripts/activate)
pip install -r requirements.txt
```

This installs [`voxport`](https://pypi.org/project/voxport/) from PyPI with
its `kokoro` extra (Kokoro and torch, about 2 GB), plus soundfile,
python-dotenv and the MCP SDK. If you're also working on voxport itself,
clone it next to this repo and run `pip install -e "../voxport[kokoro]"`
afterwards to use your checkout instead.

Check the install:

```
python generator.py --version
```

Not installed by this repo:

- **ffmpeg**: needed for MP3 output unless your `soundfile`/libsndfile
  build has native MP3 support. Put it on `PATH`. WAV output needs neither.
- **Kokoro model weights and spaCy's `en_core_web_sm`**: downloaded
  automatically on the first run. On a firewalled machine, see
  "Running behind a corporate firewall" in
  `instructions_creating_podcast_generator.md` (or `voxport`'s README) for
  an offline Hugging Face cache, and run
  `python -m spacy download en_core_web_sm` once where network access is
  available.

Optionally, copy `.env.example` to `.env` to point the inputs/outputs/archive
folders somewhere other than this repo (see "Folder configuration" below).

## Usage

### Writing a script

A script is a markdown file. Plain paragraphs are spoken. Headers,
`**Key:** value` metadata lines, horizontal rules, and italic-only lines
are stripped, so you can label sections and add notes without them being
read aloud:

```markdown
# My Episode Title

**Voice:** af_heart

## OPENING

Welcome back to the show. Today we're talking about...

## CLOSING

That's all for this episode. Thanks for listening.

---

*Source: some-article.com, September 2026.*
```

Only the two paragraphs are spoken. An italic-only line after the prose
starts ends the script, and everything after it is dropped. Keep those
lines for trailing notes. See [MANUAL.md](MANUAL.md#writing-a-script) for
the full rules.

### Running it

```
python generator.py                                   # batch: every script in inputs/
python generator.py --voice af_heart --speed 1.1      # batch, overriding voice and speed
python generator.py my-script.md --format wav --output episode01.wav   # one file
```

**Batch mode** (no file argument) converts every `.md` script in the inputs
folder (create it first; the default is `inputs/` next to `generator.py`)
and writes `<script-name>.mp3` to the outputs folder. Each script that
converts successfully is moved into the archive folder, so re-running
doesn't reprocess it. A script that fails moves to
`<archive folder>/failed/` with a `.error.txt` note, so it isn't retried
forever.

**Single-file mode** converts just the named file. `--output` only applies
here.

| Option | Meaning |
|---|---|
| `--voice VOICE` | Kokoro voice for the whole run. Overrides a script's `**Voice:**` line. Default `af_heart`. |
| `--speed FLOAT` | Speaking rate (default `1.0`; `0.9` slower, `1.1` faster). |
| `--format {mp3,wav}` | Output format (default `mp3`). |
| `--output PATH` | Output file (single-file mode only). |
| `--lang CODE` | Accent override; normally inferred from the voice name. |
| `--version` | Print the version and exit. |

Voice precedence: `--voice`, then the script's `**Voice:**` line, then
`af_heart`. The full voice catalog and troubleshooting are in
[MANUAL.md](MANUAL.md).

## Folder configuration

Defaults to `inputs/`, `outputs/`, `script_archive/` next to `generator.py`.
Override them with the Podcast Watch app (see below), or by copying
`.env.example` to `.env` and setting
`PODCAST_INPUTS_DIR`, `PODCAST_OUTPUTS_DIR`, `PODCAST_ARCHIVE_DIR` — e.g.
pointed at a folder mirrored by a cloud sync client (Sync.com, Dropbox,
etc.), so a script dropped in remotely gets picked up and the finished
audio syncs back out. **The same folders are used for both manual and
scheduled runs** — there's no separate "watch mode" config.

A typical setup points `.env` at a Sync.com/Dropbox/OneDrive-mirrored
folder (e.g. `C:\Users\yourname\Sync\podcasts\{inputs,outputs,
script_archive}`) — drop a script into `inputs/` from any device your
sync client runs on, and the finished audio syncs back out through
`outputs/`.

## Scheduled / "drop folder" mode

There's no separate watcher script. Since a run archives what it processes,
running the exact same batch command (`python generator.py`, no arguments)
on a recurring schedule *is* watch mode — each run picks up whatever's new
in the inputs folder since last time. An empty inputs folder exits 0
almost immediately (job discovery happens before any heavy import, and an
empty queue isn't treated as an error), so scheduling this every 10-15
minutes costs essentially nothing when there's nothing to do.

Only one conversion runs at a time: a run that starts while another is
still converting leaves the queue to it and exits.

The easiest way to set up the schedule is the **Set up watch** button in
the Podcast Watch app (below). It registers a Windows scheduled task named
`PodcastGeneratorWatch` for your user (no admin rights or stored password;
runs while you're logged in, including on battery) that runs
`.venv\Scripts\pythonw.exe generator.py` every 10 minutes, or whatever
interval you pick. `pythonw.exe` means no console window flashes up; the
output goes to `generator.log` in this folder instead.

Equivalently, from PowerShell:

```powershell
$repo = 'C:\path\to\podcast_generator'
$Action = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" -Argument 'generator.py' -WorkingDirectory $repo
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "PodcastGeneratorWatch" -Action $Action -Trigger $Trigger -Settings $Settings
```

To remove it: `Unregister-ScheduledTask -TaskName PodcastGeneratorWatch`.
Manual `python generator.py` runs work whether the watch is on or off.

### Turning it on/off — the Podcast Watch app

A desktop shortcut, **"Podcast Watch"**, opens a small window
(`scripts/podcast-watch.ps1`, no install needed) for day-to-day control,
so you don't need PowerShell or Task Scheduler:

- **Set up watch** (shown until the task exists) registers the
  `PodcastGeneratorWatch` task, as described above.
- **Turn ON / Turn OFF** enables or disables the task and shows its
  current state. **Check every** changes how often it runs.
- **When this app opens** can leave the watch as it was (the default), or
  always turn it on or always turn it off when the window opens. This is
  saved to `.env` as `PODCAST_WATCH_ON_OPEN=on|off`.
- **Folders** shows the inputs, outputs, and archive folders in use.
  **Browse...** picks a new one and saves it to `.env`. **Use default**
  removes the override, so the repo's own `inputs/`, `outputs/`, and
  `script_archive/` are used. **Open** opens the folder in Explorer and
  creates it if it doesn't exist yet.

The app only rewrites the keys it changes. Other `.env` lines and comments
are kept. Folder changes take effect on the next run, scheduled or manual.
See [MANUAL.md](MANUAL.md#the-podcast-watch-app) for a screenshot and
more detail.

To create the shortcut on another machine:

```powershell
$desktop = [Environment]::GetFolderPath("Desktop")
$repo = "C:\path\to\podcast_generator"
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut("$desktop\Podcast Watch.lnk")
$lnk.TargetPath = "powershell.exe"
$lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$repo\scripts\podcast-watch.ps1`""
$lnk.WorkingDirectory = $repo
$lnk.IconLocation = "shell32.dll,238"
$lnk.Save()
```

## Using it from Claude Desktop (MCP)

`mcp_server.py` is an [MCP](https://modelcontextprotocol.io) server, so an
AI app such as Claude Desktop can make podcasts directly: write a script,
queue it, convert it, and check on it, all from the chat. It runs locally
and uses the same folders and `.env` as everything else.

Add it to Claude Desktop's config (Settings → Developer → Edit Config,
which opens `claude_desktop_config.json`), then restart Claude Desktop:

```json
{
  "mcpServers": {
    "podcast-generator": {
      "command": "C:\\path\\to\\podcast_generator\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\podcast_generator\\mcp_server.py"]
    }
  }
}
```

Any other MCP client that can launch a local (stdio) server works the same
way. See [MANUAL.md](MANUAL.md#using-it-from-claude-desktop-mcp) for the
tools and an example conversation.

## Notes

- `instructions_creating_podcast_generator.md` is a narrative guide to
  writing scripts and the end-to-end workflow (by hand or drop folder),
  including script-writing style advice and corporate-firewall setup.
- `inputs/`, `outputs/`, and `script_archive/` (the local defaults) are
  gitignored — personal script drafts and generated audio aren't toolkit
  code. The real, cloud-synced versions of these folders live outside this
  repo entirely (see `.env`).
