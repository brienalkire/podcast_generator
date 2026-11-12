# Examples

## A narrated briefing

`briefing/` holds a PDF and a narration script that together make a
six-minute video introducing podcast_generator. The video linked from the
main [README](../README.md#examples) was made from these two files.

```
pip install "podcast-generator[briefing]"
podcast-generator examples/briefing/podcast-generator-intro.md
```

This needs ffmpeg on your `PATH`. The script's `**Briefing:**` line names
the PDF, which is looked for next to the script, so you can run the command
from any folder. The MP4 goes to your outputs folder (see
[Where things live](../README.md#where-things-live)), with a `.srt`
subtitle file and a `.briefing.json` timing file beside it. Add
`--output intro.mp4` to put it somewhere else.

To see how long each page will be shown, without making the video:

```
podcast-generator examples/briefing/podcast-generator-intro.md --preview
```

`briefing/sample-output/` has the subtitle and timing files from one run,
so you can see what they look like without making the video. Kokoro's
timing varies very slightly from run to run, so yours won't match to the
millisecond.

## A podcast

`podcast/neural-scaling-laws-language-statistics.md` is a single-speaker
script explaining a research paper: the one featured in the briefing.
Convert it with:

```
podcast-generator examples/podcast/neural-scaling-laws-language-statistics.md
```

The MP3 goes to your outputs folder. MP3 output usually needs ffmpeg too;
add `--format wav` for a WAV file without it.

The script is an AI-written summary of the paper, based on a summary of the
full text, as its citation line says. Check it against the paper before
relying on it.
