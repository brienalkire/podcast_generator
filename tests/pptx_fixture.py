"""Write minimal .pptx files for tests: the parts the notes reader uses."""
import zipfile

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
SLIDE_TYPE = R + "/slide"
NOTES_TYPE = R + "/notesSlide"


def _rels(items):
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{target}"/>'
                   for i, t, target in items)
    return f'<?xml version="1.0"?><Relationships xmlns="{PKG}">{body}</Relationships>'


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


LINE_BREAK = "\n"


def _run(run):
    if run == LINE_BREAK:
        return "<a:br/>"
    return "<a:r><a:t>" + _escape(run) + "</a:t></a:r>"


def make_pptx(path, slides):
    """`slides` is a list of (notes or None, hidden). Notes are a list of
    paragraphs; each paragraph is a list of text runs, LINE_BREAK for a
    line break within it."""
    with zipfile.ZipFile(path, "w") as z:
        ids = "".join(f'<p:sldId id="{256 + n}" r:id="rId{n}"/>' for n in range(1, len(slides) + 1))
        z.writestr("ppt/presentation.xml",
                   f'<?xml version="1.0"?><p:presentation xmlns:p="{P}" xmlns:r="{R}">'
                   f"<p:sldIdLst>{ids}</p:sldIdLst></p:presentation>")
        z.writestr("ppt/_rels/presentation.xml.rels",
                   _rels([(f"rId{n}", SLIDE_TYPE, f"slides/slide{n}.xml")
                          for n in range(1, len(slides) + 1)]))
        for n, (notes, hidden) in enumerate(slides, start=1):
            show = ' show="0"' if hidden else ""
            z.writestr(f"ppt/slides/slide{n}.xml",
                       f'<?xml version="1.0"?><p:sld xmlns:p="{P}"{show}><p:cSld/></p:sld>')
            if notes is None:
                continue
            z.writestr(f"ppt/slides/_rels/slide{n}.xml.rels",
                       _rels([("rId1", NOTES_TYPE, f"../notesSlides/notesSlide{n}.xml")]))
            paras = "".join("<a:p>" + "".join(_run(run) for run in para) + "</a:p>"
                            for para in notes)
            z.writestr(f"ppt/notesSlides/notesSlide{n}.xml",
                       f'<?xml version="1.0"?><p:notes xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>'
                       f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr></p:sp>'
                       f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
                       f"<p:txBody>{paras}</p:txBody></p:sp>"
                       f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="sldNum" idx="5"/></p:nvPr></p:nvSpPr>'
                       f"<p:txBody><a:p><a:r><a:t>{n}</a:t></a:r></a:p></p:txBody></p:sp>"
                       f"</p:spTree></p:cSld></p:notes>")
    return path
