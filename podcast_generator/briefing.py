"""
podcast_generator.briefing: PDF pages and narration made into an MP4.

The script side (page markers, timing) lives in generator.py; this module
reads and renders the PDF, writes subtitles, and has ffmpeg assemble the
video. Needs the `briefing` extra (pypdfium2) and ffmpeg with libx264.

PDFs are untrusted input: they're size- and page-limited, and rendered
with PDFium without initialising forms, so no embedded JavaScript runs.
"""

import json
import math
import os
import re
import shutil
import struct
import subprocess
import zlib

# The video canvas. Each page is scaled to fit and letterboxed onto it.
WIDTH, HEIGHT = 1920, 1080
FPS = 30
BACKGROUND = (0, 0, 0)
MAX_PDF_BYTES = 200 * 1024 * 1024
MAX_PDF_PAGES = 500
# Subtitle cues are split to at most this many characters (two short lines).
MAX_CUE_CHARS = 84

_MISSING_EXTRA = ('briefings need the briefing extra: '
                  'pip install "podcast-generator[briefing]"')


def _pdfium():
    try:
        import pypdfium2
    except ImportError as exc:
        raise RuntimeError(_MISSING_EXTRA) from exc
    return pypdfium2


def open_pdf(path):
    """Open a PDF for reading, with clear errors for the usual problems."""
    pdfium = _pdfium()
    if not os.path.isfile(path):
        raise ValueError(f"briefing PDF not found: {path}")
    size = os.path.getsize(path)
    if size > MAX_PDF_BYTES:
        raise ValueError(f"briefing PDF is {size // (1024 * 1024)} MB; the limit is "
                         f"{MAX_PDF_BYTES // (1024 * 1024)} MB: {path}")
    try:
        doc = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise ValueError(f"briefing PDF is password-protected; save an "
                             f"unprotected copy: {path}") from exc
        raise ValueError(f"can't read the briefing PDF ({exc}): {path}") from exc
    if len(doc) > MAX_PDF_PAGES:
        count = len(doc)
        doc.close()
        raise ValueError(f"briefing PDF has {count} pages; the limit is {MAX_PDF_PAGES}.")
    if len(doc) == 0:
        doc.close()
        raise ValueError(f"briefing PDF has no pages: {path}")
    return doc


def page_count(path):
    doc = open_pdf(path)
    try:
        return len(doc)
    finally:
        doc.close()


def page_texts(path):
    """Each page's extracted text, in order ("" for a page with no text layer)."""
    doc = open_pdf(path)
    try:
        texts = []
        for index in range(len(doc)):
            textpage = doc[index].get_textpage()
            texts.append(textpage.get_text_bounded().strip())
        return texts
    finally:
        doc.close()


def render_page(doc, number):
    """Page `number` (1-based) letterboxed onto the canvas, as an RGB array."""
    import numpy as np

    page = doc[number - 1]
    width, height = page.get_size()
    scale = min(WIDTH / width, HEIGHT / height)
    try:
        bitmap = page.render(scale=scale, rev_byteorder=True)
    except Exception as exc:  # noqa: BLE001 - PDFium's errors vary by version
        raise ValueError(f"can't render page {number} of the briefing PDF: {exc}") from exc
    pixels = bitmap.to_numpy()[:HEIGHT, :WIDTH, :3]
    canvas = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
    canvas[:] = BACKGROUND
    top = (HEIGHT - pixels.shape[0]) // 2
    left = (WIDTH - pixels.shape[1]) // 2
    canvas[top:top + pixels.shape[0], left:left + pixels.shape[1]] = pixels
    return canvas


def write_png(pixels, path):
    """Write an RGB array as a PNG, with only the standard library."""
    import numpy as np

    height, width, _ = pixels.shape
    # Each row is prefixed with filter type 0 (none).
    raw = np.zeros((height, width * 3 + 1), dtype=np.uint8)
    raw[:, 1:] = pixels.reshape(height, width * 3)

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw.tobytes(), 6)))
        f.write(chunk(b"IEND", b""))


def render_pages(pdf_path, numbers, out_dir):
    """Render pages to PNG files in `out_dir`; returns {number: path}."""
    doc = open_pdf(pdf_path)
    try:
        paths = {}
        for number in numbers:
            path = os.path.join(out_dir, f"page{number:04d}.png")
            write_png(render_page(doc, number), path)
            paths[number] = path
        return paths
    finally:
        doc.close()


def check_ffmpeg():
    """Raise RuntimeError unless ffmpeg with libx264 is on PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("briefings need ffmpeg on PATH to make the MP4. "
                           "Install it (for example: winget install ffmpeg).")
    result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                            capture_output=True, text=True, errors="replace")
    if not re.search(r"\slibx264\s", result.stdout):
        raise RuntimeError("this ffmpeg can't encode H.264 (no libx264). Install a "
                           "full build, for example: winget install ffmpeg.")


def frames_for(seconds):
    """Whole video frames covering `seconds`, so audio and video stay in step."""
    return max(1, math.ceil(seconds * FPS - 1e-9))


def subtitle_cues(spans):
    """Split [(start, end, text), ...] into cues of at most MAX_CUE_CHARS.

    Text splits at sentence ends, then between words; each piece gets a
    share of its span's time in proportion to its length.
    """
    cues = []
    for start, end, text in spans:
        pieces = []
        for sentence in re.split(r"(?<=[.!?])\s+", " ".join(text.split())):
            words, line = sentence.split(), ""
            for word in words:
                if line and len(line) + 1 + len(word) > MAX_CUE_CHARS:
                    pieces.append(line)
                    line = word
                else:
                    line = f"{line} {word}" if line else word
            if line:
                pieces.append(line)
        total = sum(len(p) for p in pieces) or 1
        at = start
        for piece in pieces:
            length = (end - start) * len(piece) / total
            cues.append((at, at + length, piece))
            at += length
    return cues


def _srt_time(seconds):
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for index, (start, end, text) in enumerate(cues, start=1):
            f.write(f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n\n")


def assemble_mp4(frames, wav_path, srt_path, out_path, work_dir):
    """Have ffmpeg make the MP4.

    `frames` is [(image path, frame count), ...] in order. The audio must
    already be exactly as long as the frames. Written to a temporary name
    first, so a half-made video never looks finished.
    """
    listing = os.path.join(work_dir, "pages.ffconcat")
    with open(listing, "w", encoding="utf-8", newline="\n") as f:
        f.write("ffconcat version 1.0\n")
        for path, count in frames:
            f.write(f"file '{os.path.basename(path)}'\nduration {count / FPS:.6f}\n")
        # The concat demuxer ignores the last entry's duration unless the
        # file is listed once more.
        f.write(f"file '{os.path.basename(frames[-1][0])}'\n")

    total = sum(count for _, count in frames)
    partial = out_path + ".part"
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", listing, "-i", wav_path]
    if srt_path:
        command += ["-i", srt_path]
    command += ["-map", "0:v", "-map", "1:a"]
    if srt_path:
        command += ["-map", "2:s", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng"]
    command += ["-c:v", "libx264", "-tune", "stillimage", "-crf", "20",
                "-pix_fmt", "yuv420p", "-r", str(FPS), "-fps_mode", "cfr",
                "-frames:v", str(total),
                "-c:a", "aac", "-b:a", "160k",
                "-movflags", "+faststart", "-f", "mp4", partial]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        if os.path.exists(partial):
            os.remove(partial)
        raise RuntimeError(f"ffmpeg couldn't make the video: {result.stderr.strip()[-800:]}")
    os.replace(partial, out_path)


def sha256(path):
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_metadata(path, info):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
        f.write("\n")
