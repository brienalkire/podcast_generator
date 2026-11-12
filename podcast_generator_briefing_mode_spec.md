# podcast_generator: Briefing Mode (draft spec)

Status: draft, revised after review against the v0.4.1 source. Function, flag and folder names below refer to the current code unless marked as new.

## 1. Goal

Given a PDF briefing and a narration script, produce a narrated MP4: each PDF page is shown while its section of the script is spoken. Script writing and briefing creation stay outside the tool. The tool only aligns, voices, and assembles.

Each section is synthesized separately, so its duration is simply its sample count. No forced alignment or timing estimation is needed.

Existing behavior is unchanged: script in, MP3 out (single-speaker and multi-speaker), through the CLI, the folder watch, and the MCP connector.

## 2. Decisions so far

- Output: MP4 only (no HTML, no narrated PPTX in this version).
- Input briefing: PDF only.
- Page markers: required (strict). No guessing, and no auto-split mode.
- Lexicon file: yes, for pronunciation fixes. Shipped first, as its own release (see §15).
- Briefing mode is additive. Audio-only podcasts remain the default path.
- A script names its PDF with a `**Briefing:**` metadata line, so the same script works in the CLI, the folder watch, and the MCP connector.

## 3. Non-goals (v1)

- Animations, transitions, embedded video, or slide builds. Pages are static images.
- PPTX input or any briefing creation. (`extract-notes`, §13, is a fast follow, not v1.)
- Burned-in subtitles.
- Cloud TTS. Everything stays local.

## 4. Interface

### The `**Briefing:**` metadata line (new)

`**Briefing:** deck.pdf` in a script makes it a briefing. A relative path resolves against the script's own folder. Like the other `**Key:**` lines, it is never spoken.

This is what lets the folder watch handle briefings: drop `deck.md` (with the line) and `deck.pdf` into the inputs folder and an MP4 comes out. Without the line, a briefing script in the inputs folder would be converted to an MP3, because batch mode picks up every `*.md`.

### CLI

There is no `briefing` subcommand. The existing parser has an optional positional `input_path`, which doesn't mix well with argparse subparsers, and a script named `briefing` would become ambiguous. Instead:

- `podcast-generator narration.md` with a `**Briefing:**` line produces `narration.mp4`.
- `podcast-generator narration.md --pdf deck.pdf` overrides (or supplies) the PDF.
- `--preview`: validate, synthesize, and print the timing table (page, words, duration) without rasterizing or encoding.
- `--lexicon FILE`: override the lexicon for this run (§8).
- `--voice`, `--speed`, `--lang` and `--output` behave as today. `--format` doesn't apply to briefings (MP4 always).

### MCP tools (connector)

- `inspect_briefing(pdf)`: returns the page count and the extracted text/title for each page, so an assistant can write correct markers. Reports pages with no text layer (scanned PDFs). This matters even when the user has attached the PDF in the chat: the assistant can read the attachment, but the server can't, and this gives the true page count of the file that will actually be used.
- `validate_briefing(script, pdf)`: dry run; returns errors and warnings without producing audio.
- `queue_podcast` gains an optional `pdf` parameter, which sets the `**Briefing:**` line, as `voice` sets `**Voice:**` today. There is no separate `queue_briefing`. `generate_now` and `podcast_status` are reused unchanged.

The PDF reaches the server as a path on the local machine, not as uploaded bytes (base64 PDFs through a tool call are heavy). The assistant should ask the user where the file is saved. On queueing, the PDF is copied into the connector queue folder next to the script, so a later edit or move of the original can't change a queued job.

## 5. Script contract

- A section starts with a marker line: `## Page N` (N is the 1-based PDF page number). Any header level works (`# Page 3`, `### Page 3`).
- A header that looks like a mistyped marker (`## Slide 3`, `## Page three`, `## Page 3: Results`) is an error in a briefing, rather than being silently dropped as an ordinary header.
- Sections must be in ascending page order.
- Text under a marker is spoken over that page. Existing metadata lines (`**Voice:**`, `**Voices:**`, `**Lexicon:**`, `**Briefing:**`) and the end-of-script italic line behave as they do today. An end-of-script italic line ends the whole script, not just its section.
- Text before the first marker is an error: there is no page to show it on.
- Do not use `---` as a section separator (the cleaner strips it).
- Optional: `## Page N (skip)` removes a page from the video (any text under it is not spoken, with a warning). Pages with no section get a short silent hold (default 3 seconds, configurable), with a warning.
- Multi-speaker scripts work inside a section, using the existing `Name: text` convention. As today, an unlabelled line continues the current speaker, and this carries across page boundaries.

### Implementation note

`_spoken_lines` (`generator.py`) currently drops every `#` line, so markers are lost. Splitting the raw text into sections and cleaning each one separately would break the end-of-script rule (`seen_prose` is tracked per call) and speaker carry-over. Instead, `_spoken_lines` yields a page event when it sees a `## Page N` line, and the existing cleaning logic stays in one place. Other headers are still dropped.

## 6. Strictness

| Situation | Behavior |
|---|---|
| No `## Page N` markers | Fail before any audio. Message states the page count and how to add markers (and mentions `inspect_briefing` / `extract-notes`). |
| Marker for a page that doesn't exist | Fail. |
| Pages out of order or duplicated | Fail. |
| Spoken text before the first marker | Fail. |
| Empty section (marker with no spoken text, not `(skip)`) | Treat as a page with no section: warn, apply silent hold. |
| Page with no section | Warn, apply silent hold. |
| Section very long for one page | Warn (over 350 words, `LONG_SECTION_WORDS`). |
| Every page marked `(skip)` | Fail. |

All errors are reported together, not just the first. With no markers at all, the "no markers" message wins over "text before the first marker".

Auto-split was dropped: "section" is undefined without markers, and strict mode plus `inspect_briefing` and `extract-notes` cover the use case.

## 7. Pipeline

1. Parse the script into page sections (§5) and validate them against the PDF's page count.
2. Apply the lexicon to each section's cleaned text (§8).
3. Synthesize each section with the existing Kokoro path. Refactor note: `process_job` concatenates every turn into one array today. Extract a `synthesize_turns(...)` that returns audio per section, used by both MP3 and MP4 assembly.
4. Each page's hold time is its audio's sample count divided by the sample rate, plus a small configurable inter-page pause.
5. Rasterize each non-skipped page to PNG with `pypdfium2` (§10).
6. Assemble the MP4 with ffmpeg (§7.1).
7. Write the outputs and a small metadata JSON: tool version, PDF hash, script hash, voices, per-page timing.

`--preview` stops after step 4 and prints the timing table. Steps 1 to 4 are testable without ffmpeg or a real PDF.

### 7.1 Video assembly

- Fixed canvas, default 1920×1080. Each page is scaled to fit and padded (letterboxed), so mixed page sizes and portrait pages work.
- Encode with `libx264 -tune stillimage -pix_fmt yuv420p` at 30 fps. Still images cost almost nothing at 30 fps, and very low frame rates confuse some players.
- If using the concat demuxer with per-image `duration` lines, list the last image twice; otherwise its duration is ignored.
- Audio is AAC, from the concatenated section audio.
- Subtitles: a sidecar `.srt`, built from the script text and section timing, plus the same track muxed in as a soft subtitle (`-c:s mov_text`). No burn-in in v1, since that needs libass and a full re-encode.

## 8. Lexicon

- Plain text, one entry per line: `written form = spoken form` (for example `JADC2 = J A D C two`). `#` starts a comment.
- Whole-word matching, case-sensitive by default.
- Applied to the cleaned text, after `_clean_inline`, so it never touches speaker labels or metadata lines.
- Inline phonemes: verified. misaki's `preprocess` parses `[word](/phonemes/)`, and voxport passes text straight to it, so a lexicon entry's spoken form may use it (`Kokoro = [Kokoro](/kˈOkəɹO/)`). `_clean_inline` strips `[text](url)` links from scripts, which is why substitution runs after cleaning.
- Locations, merged with later layers winning per entry: a user-level `lexicon.txt` in the home folder (optional), a script's `**Lexicon:**` file (relative to the script's folder), then `--lexicon` for a CLI run.
- A malformed `lexicon.txt` or `--lexicon` file fails the run before any script is touched. A bad `**Lexicon:**` file fails only that script. `queue_podcast` validates the lexicon before queueing.
- The lexicon applies to audio-only podcasts too (same code path).
- Status: implemented (step 1 of §15), unreleased.

## 9. MCP guidance for assistants

- Server instructions (sent at connect): marker format, the `**Briefing:**` line and `pdf` parameter, the end-of-script rule, target lengths, strict behavior, and asking the user for the PDF's path on disk.
- Optional prompt or resource: a briefing narration guide (how to write one section per page, pacing, avoiding reading slide text verbatim).
- Keep essential rules in tool descriptions as well, since client support for instructions and prompts varies.

## 10. Dependencies and licensing

- New dependencies go in an optional extra, `[briefing]`, so the base install stays light.
- Rasterizer: `pypdfium2`. It has a permissive license and needs no external binary. PyMuPDF (AGPL) doesn't fit an MIT package on PyPI, and `pdf2image` needs Poppler installed separately. Confirm current license terms at release time.
- ffmpeg is already needed for MP3 on most installs. For briefings it is required, with `libx264`; fail with a clear message if either is missing.
- Treat PDFs as untrusted input: page-count and file-size limits, no execution of embedded content.

## 11. Failure handling

Clear, specific messages for: missing ffmpeg or libx264, missing `[briefing]` extra, missing PDF or a `**Briefing:**` path that doesn't resolve, password-protected PDF, unreadable page, page-count mismatch, text before the first marker, lexicon syntax error (with the line number). Failed jobs go to the existing failed folder with the error recorded.

Separately, and worth fixing now whatever happens with this feature: the missing spaCy model currently surfaces as a raw error.

## 12. Test plan

- Two-page sample PDF with a matching two-section script (golden path).
- Each row of the strictness table gives the stated behavior.
- End-of-script italic line in a middle section ends the whole script.
- Speaker carry-over across a page boundary.
- Scanned PDF with no text layer (`inspect_briefing` says so).
- Multi-speaker section, lexicon substitution, skip marker, silent-hold page, mixed page sizes.
- Folder watch: `deck.md` with a `**Briefing:**` line plus `deck.pdf` in inputs produces an MP4.
- Audio-only regression: existing scripts convert identically, and the `synthesize_turns` refactor doesn't change MP3 output.
- Generate the sample PDFs in the tests (for example with `pypdfium2`'s page-creation API or a tiny checked-in fixture), not from a real deck.

## 13. PowerPoint users: extract-notes (fast follow, v1.1)

High value for PowerPoint users, but deferred so its riskiest part (hidden-slide numbering) doesn't hold up the core feature.

Many users will start from a PowerPoint deck with the narration in the speaker notes. The tool does not create the script; it only converts text that already exists.

Command: `podcast-generator --extract-notes deck.pptx [--include-hidden] [--output narration.md]` (a flag rather than a subcommand, for the same argparse reason as §4).

Behavior:
- Writes `## Page N` before each slide's notes text, ready to use as a briefing script, and a `**Briefing:** deck.pdf` line pointing at the expected PDF export.
- Numbers pages to match a PDF exported with hidden slides excluded (the PowerPoint default). With `--include-hidden`, hidden slides are kept and numbered, matching a PDF exported with "Include hidden slides" ticked.
- Skips hidden slides by default and says so in its output.
- Warns about slides with no notes (they will get a silent hold, or the user can add text).
- Reports the slide count it numbered, so the user can compare it with the PDF page count; briefing mode fails on a mismatch.
- Optional convention for cleaning notes written for a human speaker: ignore text in square brackets (stage directions such as `[pause]` or `[click]`). Flag URLs and other lines that read badly aloud.
- Reads `.pptx` only (not legacy `.ppt`). Likely implemented with `python-pptx` (verify the current API), in the `[briefing]` extra.
- Encourage the user to review the extracted script before conversion, and to add acronyms to the lexicon.

Short user-facing how-to for Windows:
1. In PowerPoint: File, then Export, then Create PDF/XPS Document (or Save As and choose PDF).
2. In Options, set "Publish what" to Slides, not Notes Pages. Leave "Include hidden slides" unticked unless you also use `--include-hidden`.
3. Run `--extract-notes` on the same `.pptx` to produce the script with page markers.
4. Check the page and section counts match, then run `podcast-generator` on the script.

Note: the notes-to-Word export and VBA macros also work but give poorer structure and are harder to share, so the utility is preferred.

## 14. Open questions

- Default silent hold (proposed 3 s) and inter-page pause lengths.
- Whether 1920×1080 should be configurable, or follow the first page's aspect ratio.
- Output folder: same outputs folder as podcasts (proposed), with `.mp4`, `.srt` and the metadata JSON side by side?

## 15. Implementation order

1. Lexicon, including the phoneme-syntax check. Releasable on its own. **Done.**
2. Page-event parsing in `_spoken_lines` and the `synthesize_turns` refactor, with `--preview` showing the timing table. No ffmpeg or PDF needed to test. **Done:** `split_pages`, `plan_pages`, `synthesize_pages`, `preview_job`. Until step 3 there is no PDF, so `--preview` runs pages up to the highest marker; `plan_pages(page_count=...)` takes the PDF's count once it exists. Defaults chosen: 0.75 s between pages, 3 s silent hold. Note: Kokoro output is not bit-identical between runs, so audio regression tests compare call sequences, not bytes.
3. Rasterizing, MP4 assembly, subtitles, the `**Briefing:**` line, and folder-watch support. **Done** (`podcast_generator/briefing.py`). Decisions made while building it:
   - Pages are rendered at the scale that fits 1920×1080 and letterboxed onto a black canvas in numpy, so every frame ffmpeg sees is the same size. Written as PNG with only `zlib` (no Pillow dependency).
   - Each page lasts a whole number of frames (rounded up), and its audio is padded to exactly that, so audio and video can't drift. Verified: frame count and audio duration match exactly.
   - x264 at CRF 20, `-tune stillimage`, 30 fps; AAC 160 kbps; `+faststart`. Written to a `.part` name and renamed when finished.
   - Subtitles: per-turn timing is exact; within a turn, cues are split at sentence ends (then words, max 84 chars) and timed in proportion to length. Sidecar `.srt` plus a `mov_text` track.
   - The PDF is rendered and ffmpeg checked before synthesis, so those failures take seconds.
   - In the inputs folder, a converted briefing's PDF is archived with the script, unless another waiting script names it. A failed briefing's PDF stays in inputs.
   - `--pdf` is single-file only; in batch mode the `**Briefing:**` line is the only way.
   - Open: `podcast_status` and `list_podcasts` still look only for audio files (step 4).
4. MCP: `inspect_briefing`, `validate_briefing`, and `queue_podcast(pdf=...)`. **Done.** Decisions:
   - PDF paths: any existing, readable `.pdf` the user names is accepted (no folder allow-list). The server is local and runs as the user, so a list would add friction without protecting anything; the size and page limits still apply.
   - `queue_podcast` also accepts an absolute path in a `**Briefing:**` line the script already has. A relative one resolves to the queue folder and is reported as not found, with a hint to ask the user for the full path.
   - The queued copy is `<name>.pdf` in the queue, and the script's line is rewritten to name it. Re-queueing the name as a plain podcast removes the old copy.
   - `queue_podcast` refuses a briefing if ffmpeg (with libx264) is missing, rather than letting the conversion fail later.
   - `validate_briefing` returns `ok: false` with the errors instead of raising, since finding problems is its purpose. `inspect_briefing` returns a `script_skeleton` with one marker per page.
   - `list_podcasts` keeps `recent_audio` as it was and adds `recent_briefings`; `podcast_status` adds `kind` ("audio" or "video"), and for a video the subtitle path and the length from `.briefing.json`.
   - Server instructions now describe the briefing flow: ask for the path, inspect, write one section per page, queue with `pdf`.
5. `extract-notes`.
