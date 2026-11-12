"""
podcast_generator.notes: PowerPoint speaker notes made into a briefing script.

`podcast-generator --extract-notes deck.pptx` writes deck.md with a
`## Page N` section per slide, holding that slide's notes, ready to pair
with the deck exported as PDF. It converts notes that already exist; it
doesn't write narration.

Reads the .pptx with only the standard library (it's a zip of XML parts).
.pptx files are untrusted input: parts are size-limited and XML with a
DOCTYPE is refused, so entity tricks can't apply.
"""

import os
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
NOTES_SLIDE_TYPE = "/notesSlide"
MAX_PART_BYTES = 20 * 1024 * 1024
MAX_SLIDES = 500

# Stage directions written for a live speaker: [pause], [click], [next slide].
BRACKETED = re.compile(r"\s*\[[^\]\n]*\]")
URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


class Slide:
    def __init__(self, number, hidden, notes):
        self.number = number    # position in the deck, 1-based, hidden ones included
        self.hidden = hidden
        self.notes = notes      # paragraphs of notes text, as written


def _read_xml(archive, name):
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_PART_BYTES:
        raise ValueError(f"part {name} is too large ({info.file_size} bytes).")
    data = archive.read(name)
    if b"<!DOCTYPE" in data[:4096].upper():
        raise ValueError(f"part {name} has a DOCTYPE, which a .pptx never needs; refusing it.")
    return ET.fromstring(data)


def _rels(archive, part):
    """{relationship id: (type, target part name)} for a part."""
    folder, base = posixpath.split(part)
    root = _read_xml(archive, posixpath.join(folder, "_rels", base + ".rels"))
    rels = {}
    if root is None:
        return rels
    for rel in root.findall("rel:Relationship", NS):
        if rel.get("TargetMode") == "External":
            continue
        target = posixpath.normpath(posixpath.join(folder, rel.get("Target", "")))
        rels[rel.get("Id")] = (rel.get("Type", ""), target)
    return rels


def _notes_text(root):
    """The notes-body paragraphs of a notes slide."""
    paragraphs = []
    for shape in root.iter(f"{{{NS['p']}}}sp"):
        placeholder = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if placeholder is None or placeholder.get("type") != "body":
            continue  # the slide picture, slide number, header or footer
        for para in shape.iter(f"{{{NS['a']}}}p"):
            pieces = []
            for node in para:
                if node.tag in (f"{{{NS['a']}}}r", f"{{{NS['a']}}}fld"):
                    pieces.append("".join(t.text or "" for t in node.iter(f"{{{NS['a']}}}t")))
                elif node.tag == f"{{{NS['a']}}}br":
                    pieces.append(" ")
            paragraphs.append("".join(pieces).strip())
    return paragraphs


def read_slides(path):
    """Every slide in deck order, with its hidden flag and notes."""
    if path.lower().endswith(".ppt"):
        raise ValueError("this is an old-style .ppt file. Open it in PowerPoint and "
                         "save it as .pptx first.")
    if not os.path.isfile(path):
        raise ValueError(f"PowerPoint file not found: {path}")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"not a .pptx file (or it's damaged): {path}") from exc
    with archive:
        presentation = _read_xml(archive, "ppt/presentation.xml")
        if presentation is None:
            raise ValueError(f"not a PowerPoint presentation: {path}")
        rels = _rels(archive, "ppt/presentation.xml")
        ids = presentation.findall("p:sldIdLst/p:sldId", NS)
        if len(ids) > MAX_SLIDES:
            raise ValueError(f"the deck has {len(ids)} slides; the limit is {MAX_SLIDES}.")
        slides = []
        for number, slide_id in enumerate(ids, start=1):
            _, slide_part = rels.get(slide_id.get(f"{{{NS['r']}}}id"), ("", None))
            slide = _read_xml(archive, slide_part) if slide_part else None
            if slide is None:
                raise ValueError(f"slide {number} is missing from the file.")
            notes = []
            for kind, target in _rels(archive, slide_part).values():
                if kind.endswith(NOTES_SLIDE_TYPE):
                    notes_root = _read_xml(archive, target)
                    if notes_root is not None:
                        notes = _notes_text(notes_root)
                    break
            slides.append(Slide(number, slide.get("show") in ("0", "false"), notes))
        return slides


def _speakable(line):
    """Keep a notes line from being read as script markdown.

    A line that would be a header, a rule, a **Key:** line or an
    italic-only line (which would end the script) is made plain.
    """
    line = line.strip()
    line = re.sub(r"^#+\s*", "", line)
    if re.fullmatch(r"([-*_])\1{2,}", line.replace(" ", "")):
        return ""
    line = re.sub(r"^\*\*([^*]+):\*\*", r"\1:", line)
    match = re.fullmatch(r"\*([^*]+)\*", line)
    return match.group(1) if match else line


def notes_to_script(slides, title, pdf_name, include_hidden=False):
    """Return (script text, report lines)."""
    shown = [s for s in slides if include_hidden or not s.hidden]
    hidden = [s.number for s in slides if s.hidden]
    if not shown:
        raise ValueError("every slide is hidden. Use --include-hidden, or unhide some.")

    lines = [f"# {title}", "", f"**Briefing:** {pdf_name}", ""]
    no_notes, urls, brackets = [], [], 0
    for page, slide in enumerate(shown, start=1):
        lines += [f"## Page {page}", ""]
        paragraphs = []
        for paragraph in slide.notes:
            brackets += len(BRACKETED.findall(paragraph))
            text = _speakable(BRACKETED.sub("", paragraph))
            if text:
                paragraphs.append(text)
        if not paragraphs:
            no_notes.append(page)
        if any(URL.search(p) for p in paragraphs):
            urls.append(page)
        for text in paragraphs:
            lines += [text, ""]

    report = [f"Numbered {len(shown)} slide(s) as pages 1 to {len(shown)}."]
    if hidden and not include_hidden:
        report.append(f"Left out hidden slide(s) {_list(hidden)}, as PowerPoint's PDF "
                      "export does by default. Use --include-hidden if your PDF has them.")
    elif hidden:
        report.append(f"Kept hidden slide(s) {_list(hidden)}: export the PDF with "
                      "\"Include hidden slides\" ticked so the pages match.")
    if no_notes:
        report.append(f"Warning: page(s) {_list(no_notes)} have no notes; they'll be "
                      "shown silently unless you add narration.")
    if urls:
        report.append(f"Warning: page(s) {_list(urls)} have web addresses, which read "
                      "badly aloud. Reword them.")
    if brackets:
        report.append(f"Removed {brackets} [bracketed] stage direction(s).")
    report.append("Check that the PDF has the same number of pages, review the script, "
                  "and add any acronyms to your lexicon before converting.")
    return "\n".join(lines).rstrip() + "\n", report


def _list(numbers):
    return ", ".join(str(n) for n in numbers)


def extract_notes(pptx_path, output_path=None, include_hidden=False):
    """Write the script next to the deck (or to `output_path`); returns (path, report)."""
    slides = read_slides(pptx_path)
    base = os.path.splitext(os.path.basename(pptx_path))[0]
    output_path = output_path or os.path.join(os.path.dirname(os.path.abspath(pptx_path)),
                                              base + ".md")
    if os.path.exists(output_path):
        raise ValueError(f"{output_path} already exists. Move it, or pick another "
                         "name with --output.")
    script, report = notes_to_script(slides, base, base + ".pdf", include_hidden)
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(script)
    return output_path, report
