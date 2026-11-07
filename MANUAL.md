# podcast_generator — User Manual

A companion to [README.md](README.md) — that file gets you running in five
minutes; this one covers everything else: how to write a script, the full
CLI reference, the voice catalog, the Podcast Watch desktop app, using it
from Claude Desktop (MCP), and troubleshooting.

## What this does

`podcast-generator` takes a markdown file — a podcast script — and turns it
into an audio file (MP3 or WAV) using [Kokoro](https://github.com/hexgrad/kokoro),
a free, open-source text-to-speech model that runs entirely on your own
machine via [`voxport`](https://github.com/brienalkire/voxport). No API key, no per-use cost, and
(once the model is cached) no internet connection required.

## Writing a script

Any markdown file works, but a few conventions control exactly what gets
spoken aloud versus stripped out before synthesis:

- **Headers** (`#`, `##`, `###`, ...) are removed entirely — including
  their text. If you use headers as section labels (`## OPENING`,
  `## CLOSING`), those labels are *not* spoken.
- **Metadata lines** matching `**Key:** value` (e.g. `**Author:** ...`,
  `**Date:** ...`) are removed. This is also how `**Voice:** af_heart`
  works — see below.
- **Horizontal rules** (`---`, `***`, `___`) are removed.
- **An entirely-italic line** (e.g. `*Source: ...*` or `*End of script.*`)
  is a production note. Before any spoken prose it's skipped as front
  matter. After prose has started it's the end-of-script marker, and
  **everything from that line to the end of the file is dropped, not just
  that line.** This is meant for a trailing citation or production note,
  but it's a common gotcha: if a normal sentence in the middle of your
  script happens to be wrapped entirely in `*asterisks*`, everything after
  it will silently go unspoken. Keep italic-only lines for the very top or
  very end of the file only.
- **Inline formatting** — `**bold**`, `*italic*`, `` `code` ``,
  `[link text](url)` — has its markup stripped but the text itself is
  kept and spoken normally.
- Blank lines are preserved as paragraph breaks; runs of 3+ blank lines
  collapse to one.

Everything else — plain paragraphs — is spoken as-is. A minimal script:

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

Only "Welcome back to the show..." and "That's all for this episode..."
get spoken — the title, section labels, voice metadata, and trailing
source note are all stripped.

### Choosing a voice

Precedence, highest to lowest:

1. `--voice` on the command line — applies to every script in that run.
2. A `**Voice:**` line in the script's own header.
3. The built-in default (`af_heart`).

This lets you set a default for most episodes while overriding specific
ones — e.g. a recurring segment that always uses a different voice.

## Full CLI reference

```
podcast-generator [input_script.md] [options]
```

| Argument | Meaning |
|---|---|
| `input_script.md` (positional, optional) | Convert just this one file instead of batch-processing the inputs folder. |
| `--voice VOICE` | Kokoro voice for the whole run (see catalog below). Overrides any `**Voice:**` line. |
| `--lang CODE` | Accent code (`a` American, `b` British). Defaults to the chosen voice's first letter — you'd only override this for an edge case. |
| `--speed FLOAT` | Speaking rate multiplier (default `1.0`; `0.9` slower, `1.1` faster). |
| `--format {mp3,wav}` | Output format (default `mp3`). |
| `--output PATH` | Output file path. Only used in single-file mode; ignored in batch mode. |
| `--version` | Print the installed version and exit. |

`python -m podcast_generator` does the same thing.

**Batch mode** (no positional argument): every `.md` file in the inputs
folder is converted, written to the outputs folder as
`<script-name>.<format>`, and (on success) moved to the archive folder.

**Single-file mode**: pass a path directly. `--output` only applies here.
Archiving still happens if the file you named happens to live in the
inputs folder; a file from anywhere else is left where it is.

## Voice catalog

Kokoro's voice names encode accent and gender in the first two letters
(`a`=American/`b`=British, `m`=male/`f`=female). These are the voices this
tool validates against and shows in `--help`:

| American male | American female | British male | British female |
|---|---|---|---|
| `am_onyx` | `af_heart` | `bm_george` | `bf_emma` |
| `am_adam` | `af_bella` | `bm_lewis` | `bf_isabella` |
| `am_echo` | `af_nova` | `bm_daniel` | `bf_alice` |
| `am_eric` | `af_sarah` | `bm_fable` | `bf_lily` |
| `am_fenrir` | `af_sky` | | |
| `am_liam` | `af_nicole` | | |
| `am_michael` | `af_aoede` | | |
| `am_puck` | `af_kore` | | |

We don't have authoritative per-voice character descriptions beyond the
defaults chosen for this project (`af_heart` for most episodes, `am_echo`
for one recurring series) — try a few on a short script and pick what
sounds right for your content. Kokoro supports more voices than this list
(including other languages); this tool's `--voice` choices are
deliberately limited to a curated English subset. If you need one outside
this list, it'll need adding to `VOICE_CHOICES` in
`podcast_generator/generator.py`.

**Only voices already in the local Hugging Face cache work on a machine
with `HF_HUB_OFFLINE=1` set.** On a machine with normal internet access, an
uncached voice just downloads on first use. See "Offline use" below.

## Scheduled ("drop folder") mode

Running `podcast-generator` on a schedule turns the inputs folder into a
drop folder. Each run converts whatever scripts have arrived since the last
one and archives them, so nothing is processed twice. Point the folders at
a cloud-synced location and you can drop a script in from any device and
get the finished audio back out, with no manual run.

The schedule is a Windows scheduled task named `PodcastGeneratorWatch`
that runs every few minutes. Create it once with the **Set up watch**
button in the Podcast Watch app below, then use the same app to control
it. On macOS or Linux, schedule `podcast-generator` with cron or similar
instead; the app and the scheduled task are Windows-only.

Only one conversion runs at a time on a machine. If a run starts while
another is still converting, for example a scheduled check during a long
script, it leaves the queue to the run already going and exits.

## The Podcast Watch app

A small window for day-to-day control of the drop folder. Open it with
the `podcast-watch` command, or from a desktop shortcut that
`podcast-watch --shortcut` creates for you. It's a Windows PowerShell
script shipped inside the package (`podcast_generator/podcast-watch.ps1`),
so there's nothing else to install.

![The Podcast Watch window, showing the watch turned on and the three folders](docs/images/podcast-watch.png)

The **About** menu at the top shows the version number and the author.

### Folder watch

- **Watch is ON / OFF** shows whether the scheduled task is enabled. When
  it's on, the line underneath gives the check interval.
- **Turn ON / Turn OFF** enables or disables the task. Turning it off only
  stops the schedule. Scripts already in the inputs folder stay there and
  are converted when you turn it back on. Manual `podcast-generator` runs
  work either way.
- **When this app opens** decides what happens to the watch each time you
  open the window:
  - *Leave watch as it was* (the default) changes nothing.
  - *Turn watch ON* always switches it on, so opening the app is enough to
    start the watch.
  - *Turn watch OFF* always switches it off.

  The choice is saved immediately to `.env` as `PODCAST_WATCH_ON_OPEN`.
- **Check every** sets how often the watch looks for new scripts (5 to 60
  minutes). The change applies to the scheduled task straight away and
  doesn't turn the watch on or off.

#### Setting up the watch

On a machine where the watch has never been set up, the window says
**Watch not set up** and the button reads **Set up watch**. Pick an
interval under **Check every**, then click the button. The app registers
the `PodcastGeneratorWatch` scheduled task and turns it on. The task:

- runs under your own Windows account, with no admin rights or stored
  password, and only while you're logged in;
- runs on battery power as well as when plugged in;
- runs `pythonw.exe -m podcast_generator` from the Python environment you
  started the app from, so no console window flashes up on each check.
  Each run's output is appended to `generator.log` in the home folder
  (see "Where settings are stored" below).

If you later move or recreate that environment, delete the task and set it
up again from the new one.

To remove the task, run
`Unregister-ScheduledTask -TaskName PodcastGeneratorWatch` in PowerShell
or delete it in Task Scheduler. The app then offers **Set up watch** again.

### Folders

The three folders `podcast-generator` uses, whether it runs on the schedule or
by hand:

| Folder | What goes there |
|---|---|
| **Inputs** | Scripts (`.md` files) waiting to be converted. |
| **Outputs** | Finished audio, named after the script (`my-episode.mp3`). |
| **Archive** | Scripts after conversion. Scripts that failed go to `failed/` inside it, each with a `.error.txt` note. |

For each folder:

- **Browse...** picks a different folder and saves it to `.env`.
- **Open** opens the folder in File Explorer, creating it first if it
  doesn't exist yet.
- **Use default** removes your choice from `.env`, so the folder goes back
  to the one inside the home folder (`inputs/`, `outputs/`, or
  `script_archive/`). The label then reads "(default)" and the button is
  greyed out.

Changes take effect on the next run. There's nothing to restart.

### Where settings are stored

Settings live in `.env` in the **home folder**, which also holds the
default `inputs/`, `outputs/` and `script_archive/` folders and
`generator.log`. The home folder is:

- `podcast_generator` in your Documents folder, for a `pip install`;
- the repo folder, when running from a source checkout;
- or whatever `PODCAST_GENERATOR_HOME` points to, if you set that
  environment variable (it can't go in `.env` itself).

Everything the app saves goes into that `.env`, the same file
`podcast-generator` reads:

```
PODCAST_INPUTS_DIR=C:\Users\yourname\Sync\podcasts\inputs
PODCAST_OUTPUTS_DIR=C:\Users\yourname\Sync\podcasts\outputs
PODCAST_ARCHIVE_DIR=C:\Users\yourname\Sync\podcasts\script_archive
PODCAST_WATCH_ON_OPEN=on
```

The app changes only these lines and leaves the rest of the file,
including comments, as it was. You can still edit `.env` by hand;
[`.env.example`](.env.example) documents every setting. Each machine keeps
its own `.env`.

## Using it from Claude Desktop (MCP)

`podcast-generator-mcp` lets an AI app that supports the
[Model Context Protocol](https://modelcontextprotocol.io), such as Claude
Desktop, make podcasts for you. You can ask, for example, "write a
10-minute episode explaining how tides work, read by a British voice", and
the app writes the script, queues it, converts it, and tells you where the
MP3 is. Everything still runs on your machine, using the same folders and
`.env` as the command line and the Podcast Watch app.

### Setting it up

1. Install with the `mcp` extra, somewhere that won't move or get deleted.
   A [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/) tool
   install is the simplest:

   ```
   uv tool install "podcast-generator[mcp]"
   ```

   or `pipx install "podcast-generator[mcp]"`. Both put the commands in
   `~/.local/bin` (`%USERPROFILE%\.local\bin` on Windows). A regular virtual
   environment works too, as long as it stays where it is.
2. Print the Claude Desktop config for that install:

   ```
   podcast-generator-mcp --config
   ```

   This prints an `mcpServers` entry with the command's full path, which
   Claude Desktop needs because it doesn't see your shell's `PATH`. If
   `PODCAST_GENERATOR_HOME` is set when you run it (see "Where things
   live"), the entry passes it on too, since Claude Desktop doesn't see your
   shell's environment variables either. Example output on Windows:

   ```json
   {
     "mcpServers": {
       "podcast-generator": {
         "command": "C:\\Users\\you\\.local\\bin\\podcast-generator-mcp.exe"
       }
     }
   }
   ```

3. In Claude Desktop, open Settings → Developer → Edit Config, which opens
   `claude_desktop_config.json`. If the file has no `mcpServers` section,
   add the printed one at the top level; if it has one, add the
   `"podcast-generator"` entry inside it. Keep everything else in the file.
4. Fully quit Claude Desktop (on Windows, right-click its system-tray icon
   and choose Quit; closing the window isn't enough) and start it again.
   Claude Desktop reads the config only when it starts.

Other MCP clients that can start a local (stdio) server use the same
command.

### Checking it's installed

After restarting Claude Desktop:

- **Settings → Developer** lists `podcast-generator`. It should say it's
  running. If it says it failed, see "Troubleshooting" below.
- **In a chat**, open the connectors (or tools) menu in the chat box, from
  the `+` or tools button. `podcast-generator` is listed with its six tools,
  and its switch should be on.
- **A quick test**: start a new chat and ask

  > Use podcast-generator to make a 1-minute podcast about why the sky is
  > blue, using a British voice, and tell me where the MP3 is.

  Claude should list the voices, queue a script, start the conversion, and
  report an MP3 in your outputs folder within a minute or two.

### Using it

Ask for what you want in plain language. Claude writes the script and runs
the tools. For example:

- "Make a 10-minute episode explaining how tides work, read by a British
  male voice. Call it science-ep01-tides."
- "Turn these notes into a 5-minute podcast script, show me the script
  first, then make the audio." (Then paste or attach the notes.)
- "What voices can podcast-generator use?"
- "What podcasts have I made recently? Did any fail?"
- "Requeue science-ep01-tides with replace=true and generate it again."
- "Turn the podcast watch on." (Windows, once the watch is set up.)

What to expect:

- **Approval prompts.** The first time Claude uses each tool, Claude
  Desktop asks whether to allow it. Choose to always allow if you don't
  want to be asked again.
- **The first conversion is slower.** Loading the model takes about a
  minute. On the very first run, Kokoro's model and voice and spaCy's
  English model (`en_core_web_sm`) are also downloaded (see "Offline use"
  if your network blocks that). After that, a script takes roughly a tenth
  of its audio length to convert.
- **Claude waits for you.** It follows the conversion with
  `podcast_status` and tells you when the MP3 is ready, with its path,
  size, and length. Long episodes take several checks. You can keep
  chatting, or come back and ask "is science-ep01-tides done?"
- **Where things go.** Scripts are saved to the inputs folder, audio to
  the outputs folder, and converted scripts are moved to the archive (see
  "Where things live"). Ask "where are my podcast folders?" to see the
  paths. A script that fails goes to `script_archive/failed`, next to a
  `.error.txt` file giving the reason.
- **Names are unique.** Queuing a name that already has a script or audio
  is refused unless you say to replace it.

### Upgrading

Quit Claude Desktop fully first, because it keeps `podcast-generator-mcp`
running and Windows won't let the files be replaced while it's in use.
Then:

```
uv tool upgrade podcast-generator
```

(or `pipx upgrade podcast-generator`), and start Claude Desktop again. The
config doesn't change, since the command path stays the same.

### Tools

| Tool | What it does |
|---|---|
| `list_voices` | Lists the voices a script can use. |
| `queue_podcast` | Saves a script to the inputs folder under a name you choose, optionally setting its voice. It checks the script first: an unknown voice, a script with nothing to speak, or a name that's already taken is reported straight away, not after a failed conversion. Returns the word count and an estimated length. |
| `generate_now` | Starts converting everything queued, in the background, and returns at once. Does nothing if a conversion is already running. |
| `podcast_status` | Reports whether a podcast is queued, converting, done (with the file path, size, and length), or failed (with the reason). With `wait_seconds` (up to 50), it waits for a conversion to finish before answering, returning as soon as it's done or failed. |
| `list_podcasts` | Shows the folders, whether the watch is on, what's queued, and recent audio and failures. |
| `set_watch` | Turns the scheduled watch on or off. |

Conversion never happens inside a tool call, because a long script takes
minutes. If the watch is on, a queued script is picked up on the next
check. Otherwise the AI calls `generate_now`. Either way, it follows the
conversion with `podcast_status`, passing `wait_seconds` so each call
waits up to 50 seconds instead of the AI needing a separate way to pause.
Output from conversions started this way goes to `generator.log` in the
home folder.

## Offline use

Kokoro downloads its model weights, and each voice pack (e.g.
`af_heart.pt`), from Hugging Face the first time each is used. They're
cached in Hugging Face's standard location (`~/.cache/huggingface`), or
wherever `HF_HOME` points. To run on a machine that can't reach
huggingface.co:

1. On a machine with internet access, add `HF_HOME=<some folder>` to the
   home folder's `.env`, then convert a short script once with each voice
   you'll need. The model and those voices land in that folder.
2. Copy the folder to the offline machine and add `HF_HOME=<where you put
   it>` to that machine's `.env`.
3. Add `HF_HUB_OFFLINE=1` to the offline machine's `.env`. Only cached
   voices work there.
4. Install spaCy's English model while you have a network connection,
   since `HF_HUB_OFFLINE` doesn't cover it:
   `python -m spacy download en_core_web_sm`.

### Behind a corporate firewall or proxy

The first run downloads from three places: Kokoro's model and voices from
Hugging Face (huggingface.co, plus its Xet CDN at addresses like
`us.aws.cdn.hf.co`), and spaCy's English model from GitHub. Firewalls often
break one of them. Each fix below is a line in the home folder's `.env`,
which podcast_generator loads before anything is downloaded.

- **`CERTIFICATE_VERIFY_FAILED`**: an SSL-inspecting proxy is replacing
  certificates with your company's own. Point Python at your company's CA
  certificate chain (a `.pem` file; your IT department can supply it):

  ```
  SSL_CERT_FILE=C:\path\to\corporate-ca-chain.pem
  REQUESTS_CA_BUNDLE=C:\path\to\corporate-ca-chain.pem
  ```

  Alternatively, `pip install pip-system-certs` makes Python trust
  Windows' certificate store, which usually already includes your
  company's certificate.
- **`403` from an address like `us.aws.cdn.hf.co` while downloading the
  model**: the network blocks Hugging Face's Xet CDN. Have Hugging Face
  use plain HTTP downloads from huggingface.co instead:

  ```
  HF_HUB_DISABLE_XET=1
  ```

- **"Can't find model 'en_core_web_sm'" because GitHub is blocked**:
  spaCy downloads its model from GitHub. Hugging Face hosts a copy:
  download
  `https://huggingface.co/spacy/en_core_web_sm/resolve/main/en_core_web_sm-any-py3-none-any.whl`
  and install it in the same environment with
  `python -m pip install --no-deps en_core_web_sm-any-py3-none-any.whl`.
  That copy is version 3.7.1, built for spaCy 3.7, so spaCy 3.8 may warn
  that it's for an older version. It works with Kokoro despite the
  warning. If your network allows GitHub, `python -m spacy download
  en_core_web_sm` gets the matching version.

## Managed or locked-down computers

Some work computers run endpoint-security software that checks each new
file or program, or IT policies that block new executables. A full install
writes tens of thousands of files (torch alone is about 2 GB), which can
mean a flood of approval prompts, or files that Python can't read
afterwards ("Permission denied", or `torch\lib\c10.dll` failing to load).
Two things help.

**Reuse an environment that already has the heavy packages.** If a Python
environment your IT already trusts has torch, kokoro, and spaCy (for
example a conda/miniforge install), add just podcast_generator and voxport
to it, without letting pip pull in or upgrade anything else:

```
python -m pip install --no-deps voxport podcast-generator
python -m pip check
```

`pip check` lists anything still missing. podcast_generator itself needs
`numpy` (1.26 or later; podcast_generator 0.3.5 and voxport 0.5.2 onward), `soundfile`, `python-dotenv` and `platformdirs`;
voxport's Kokoro support needs `kokoro` and `torch`; the MCP server needs
`mcp`. Install any that are missing the same way, one at a time, with
`--no-deps`.

**Use `python -m` instead of the command launchers.** If
`podcast-generator.exe` gives "Permission denied" or is blocked as an
unsigned program, run the same commands through Python, which is already
trusted:

| Command | Launcher-free equivalent |
|---|---|
| `podcast-generator` | `python -m podcast_generator` |
| `podcast-watch` | `python -m podcast_generator.watch` |
| `podcast-generator-mcp` | `python -m podcast_generator.mcp_server` |

`python -m podcast_generator.mcp_server --config` prints a Claude Desktop
config that starts the MCP server this way, using `python.exe` and `-m`
instead of the launcher.

## Troubleshooting

**Podcast Watch says "Watch not set up"**: The `PodcastGeneratorWatch`
scheduled task doesn't exist on this machine yet. Click **Set up watch**
(see "Setting up the watch" above).

**"Could not set up the podcast watch"**: Windows refused to create the
task, and the message gives Windows' reason. Some work computers block
scheduled tasks for ordinary users; if so, run `podcast-generator` by
hand or ask your IT department.

**The podcast-generator tools don't appear in Claude Desktop**: Check that
the command path in `claude_desktop_config.json` exists (rerun
`podcast-generator-mcp --config` to get the current one), that backslashes
are doubled, that the entry is inside `mcpServers`, and that you fully quit
and restarted Claude Desktop. Claude Desktop's MCP
log (Settings → Developer) shows the server's startup errors. A common one
is "podcast-generator-mcp needs the MCP SDK", fixed by reinstalling with the
extra: `uv tool install --force "podcast-generator[mcp]"` (or
`pip install "podcast-generator[mcp]"` in that environment).

**Claude Desktop won't quit, or has no tray icon**: Sometimes Quit leaves
Claude Desktop running in the background with no window and no tray icon,
so it never rereads its config. Check Task Manager for `Claude` processes
and end them, or run this in PowerShell:

```
Get-Process claude | Where-Object Path -like '*WindowsApps*' | Stop-Process
```

(The `WindowsApps` filter keeps it from touching Claude Code, which also
runs as `claude.exe`.) Then start Claude Desktop again.

**podcast-generator shows as failed after an upgrade**: The upgrade ran
while Claude Desktop was using the files, and was only partly applied.
Quit Claude Desktop fully, run
`uv tool install --force "podcast-generator[mcp]"`, and start it again.

**"Can't find model 'en_core_web_sm'"**: spaCy's English model couldn't be
installed on the first run. Versions before 0.3.2 had this problem under
`uv tool install`, which has no pip; upgrade (see "Upgrading" above). On a
network that blocks the download, see "Offline use". Then requeue the
script from `script_archive/failed` with replace=true.

**"Could not turn the podcast watch on/off"**: Windows refused to change
the scheduled task, and the message gives Windows' reason. If the task was
registered by another user or by an administrator, you may need to enable
or disable it in Task Scheduler instead.

**Nothing happens when the watch is on**: Check that a run has had time to
happen (the app shows the interval), that the script ends in `.md`, and
that it's in the inputs folder the app shows. If the script was picked up
but failed, it's in the archive folder's `failed/` subfolder with a
`.error.txt` note explaining why. Otherwise, look at the end of
`generator.log` in the home folder for the latest run's output.

**"Another conversion run is already in progress"**: Not an error. Only one
conversion runs at a time; the run already going converts the queue. In
single-file mode, try again when it finishes.

**"No .md scripts found in ..."** — Not an error (exit code 0). The
inputs folder is just empty right now. Normal for a scheduled run between
drops.

**"script requests unknown voice '...'"** — A `**Voice:**` line names
something not in the catalog above. Check spelling (underscore, not
hyphen: `af_heart` not `af-heart`).

**"no spoken text found after stripping the markdown"** — Usually means
an italic-only line partway through the script triggered the
end-of-script cutoff (see "Writing a script" above) and everything after
it — possibly the entire rest of the file — got dropped. Check for a
stray `*line wrapped entirely in asterisks*` before the content you
expected to hear.

**MP3 write fails, mentions ffmpeg** — Your `soundfile`/libsndfile build
doesn't have native MP3 support and `ffmpeg` isn't on `PATH`. Either
install `ffmpeg`, or use `--format wav` (needs neither).

**First run on a new machine hangs or fails trying to reach the
network** — A fresh Python environment downloads a small spaCy model (`en_core_web_sm`) on first use, separately from the
Kokoro model itself. On a firewalled machine, run
`python -m spacy download en_core_web_sm` ahead of time, while you still
have a network connection somewhere.

**A voice fails with a Hub connection error instead of downloading** —
`HF_HUB_OFFLINE=1` is set (intentionally, on a firewalled machine) and
that voice isn't in the local Hugging Face cache. Either populate the cache with
that voice's `.pt` file from a machine that can reach huggingface.co, or
unset `HF_HUB_OFFLINE` if this machine actually has internet access.
