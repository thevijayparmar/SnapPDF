"""
SnapPDF - "Keep only..." reduction modes.

Two extra, more aggressive reductions on top of the normal Structure /
Metadata / Images pipeline in engine.py. Both are DESTRUCTIVE by design -
the user is explicitly asking to throw content away for maximum size
reduction, not to preserve visual fidelity.

  keep_text_and_vectors()  - strip every raster image, keep everything
                             else exactly as-is (text, vector art, fonts,
                             annotations). Cheap: same page objects, just
                             delete image XObjects.

  keep_text_only()         - the aggressive one. Every page is rebuilt
                             from scratch: extract each character's
                             Unicode value, position and size (pypdfium2's
                             text page), then redraw ONLY the text using
                             one of the 14 standard PDF fonts (no
                             embedding needed - every PDF reader ships
                             these). Images, vector paths, annotations,
                             forms and metadata are all gone; nothing
                             survives but text.

Why redraw instead of edit the content stream in place: real-world PDFs
almost always use embedded SUBSET fonts (e.g. "ABCDEF+Calibri"). Renaming
the font resource to a standard font while keeping the original character
codes produces garbage, because subset fonts remap character codes
arbitrarily. Extracting actual Unicode text via pdfium and laying it out
fresh sidesteps that entirely - at the cost of layout being an
approximation (line/word positions are preserved; kerning, exact glyph
widths, ligatures are not).
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from pathlib import Path

from .analysis import validate_pdf

# ---------------------------------------------------------------------------
# Base-14 font selection
# ---------------------------------------------------------------------------

# Every PDF reader can render these without any embedded font data.
_BASE14 = {
    ("serif", False, False):  "Times-Roman",
    ("serif", True, False):   "Times-Bold",
    ("serif", False, True):   "Times-Italic",
    ("serif", True, True):    "Times-BoldItalic",
    ("sans", False, False):   "Helvetica",
    ("sans", True, False):    "Helvetica-Bold",
    ("sans", False, True):    "Helvetica-Oblique",
    ("sans", True, True):     "Helvetica-BoldOblique",
    ("mono", False, False):   "Courier",
    ("mono", True, False):    "Courier-Bold",
    ("mono", False, True):    "Courier-Oblique",
    ("mono", True, True):     "Courier-BoldOblique",
}

_SERIF_HINTS = ("times", "serif", "georgia", "garamond", "cambria", "book",
                "minion", "palatino", "constantia")
_MONO_HINTS = ("courier", "mono", "consolas", "typewriter")


def _classify_font(base_name: str) -> tuple[str, bool, bool]:
    """PDF font BaseFont string (e.g. 'ABCDEF+Calibri-Bold') -> (family
    bucket, is_bold, is_italic). Subset prefixes ('ABCDEF+') are stripped
    first. Defaults to sans/regular when nothing matches - the common case
    for body text (Arial/Calibri/Helvetica-family fonts)."""
    name = base_name.split("+", 1)[-1] if "+" in base_name else base_name
    low = name.lower()
    bold = "bold" in low or "black" in low or "heavy" in low or "semibold" in low
    italic = "italic" in low or "oblique" in low
    family = "sans"
    if any(h in low for h in _SERIF_HINTS):
        family = "serif"
    elif any(h in low for h in _MONO_HINTS):
        family = "mono"
    return family, bold, italic


def _base14_font(base_name: str) -> str:
    fam, bold, italic = _classify_font(base_name or "")
    return _BASE14[(fam, bold, italic)]


# ---------------------------------------------------------------------------
# Character -> line-run grouping
# ---------------------------------------------------------------------------

@dataclass
class _Run:
    text: str
    x: float
    y: float           # baseline-ish (bottom of first char box)
    size: float
    font: str           # base-14 PostScript name


def _extract_runs(textpage, page_height: float) -> list[_Run]:
    """Walk every character on the page and coalesce them into runs: a run
    is a maximal sequence of chars with the same (rounded) font, size and
    baseline that are horizontally contiguous. This is deliberately simple
    - no paragraph/column detection - each visual "line" in the source
    becomes one or more runs, which is enough to reproduce the reading
    order and approximate layout."""
    n = textpage.count_chars()
    runs: list[_Run] = []
    cur_text = ""
    cur_x0 = cur_y0 = cur_size = None
    cur_font = None
    last_right = None
    last_top = None

    def flush():
        nonlocal cur_text, cur_x0, cur_y0, cur_size, cur_font
        if cur_text.strip():
            runs.append(_Run(cur_text, cur_x0, cur_y0, cur_size, cur_font))
        cur_text = ""
        cur_x0 = cur_y0 = cur_size = None
        cur_font = None

    for i in range(n):
        ch = textpage.get_text_range(i, 1)
        if ch == "":
            continue
        try:
            left, bottom, right, top = textpage.get_charbox(i)
        except Exception:
            continue
        obj = textpage.get_textobj(i)
        size = obj.get_font_size() if obj is not None else 10.0
        base_name = ""
        try:
            if obj is not None:
                base_name = obj.get_font().get_base_name() or ""
        except Exception:
            pass
        font = _base14_font(base_name)

        is_space_like = ch in ("\r", "\n")
        if is_space_like:
            flush()
            last_right = None
            continue

        same_line = (cur_y0 is not None and abs(bottom - cur_y0) < max(1.5, size * 0.35)
                     and cur_size is not None and abs(size - cur_size) < 0.6
                     and cur_font == font)
        # a big horizontal gap (more than ~1.5x the char width) starts a new run
        gap_ok = last_right is None or (left - last_right) < max(size * 1.5, 6)

        if cur_text and same_line and gap_ok:
            # insert a real space if pdfium left a visible gap without a space char
            if last_right is not None and (left - last_right) > size * 0.28 \
                    and not cur_text.endswith(" ") and ch != " ":
                cur_text += " "
            cur_text += ch
        else:
            flush()
            cur_x0, cur_y0, cur_size, cur_font = left, bottom, size, font
            cur_text = ch
        last_right = right
        last_top = top
    flush()
    return runs


# ---------------------------------------------------------------------------
# PDF escaping for literal strings
# ---------------------------------------------------------------------------

def _pdf_escape(s: str) -> tuple[bytes, bool]:
    """Encode text for a PDF literal string using a Latin-1 (WinAnsi-ish)
    fallback - base-14 fonts are simple 8-bit fonts with no Unicode CMap.
    Characters outside Latin-1 become '?'. Returns (encoded_bytes,
    had_substitution) so callers can warn when non-Latin text (Cyrillic,
    CJK, Arabic, Devanagari, etc.) was present - Keep-only-Text is not a
    safe choice for those documents."""
    out = bytearray()
    substituted = False
    for ch in s:
        code = ord(ch)
        if code > 255:
            code = ord("?")
            substituted = True
        b = bytes([code])
        if b in (b"(", b")", b"\\"):
            out += b"\\" + b
        else:
            out += b
    return bytes(out), substituted


# ---------------------------------------------------------------------------
# Result object (mirrors engine.Result closely so the GUI/daemon can share
# the same reporting code)
# ---------------------------------------------------------------------------

@dataclass
class TextModeResult:
    source: str
    ok: bool
    output: str | None = None
    error: str | None = None
    in_bytes: int = 0
    out_bytes: int = 0
    pages: int = 0
    chars_kept: int = 0
    non_latin_detected: bool = False   # True = some characters had to be
                                       # replaced with '?' (base-14 fonts
                                       # can't represent non-Latin script)
    seconds: float = 0.0

    def summary(self) -> str:
        if not self.ok:
            return f"FAIL  {Path(self.source).name}: {self.error}"
        saved = (1 - self.out_bytes / self.in_bytes) * 100 if self.in_bytes else 0
        note = "  [non-Latin text was replaced with '?']" if self.non_latin_detected else ""
        return (f"OK    {Path(self.source).name} -> {Path(self.output).name}  "
                f"{self.in_bytes/1024:.0f}KB -> {self.out_bytes/1024:.0f}KB "
                f"({saved:+.0f}%)  {self.chars_kept} chars kept{note}")


def _unique(candidate: Path) -> Path:
    n = 1
    stem, ext, folder = candidate.stem, candidate.suffix, candidate.parent
    while candidate.exists():
        candidate = folder / f"{stem}-{n}{ext}"
        n += 1
    return candidate


def _output_path(src: Path, suffix: str, output_dir: str | None = None) -> Path:
    folder = Path(output_dir) if output_dir else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    return _unique(folder / f"{src.stem}{suffix}.pdf")


# ---------------------------------------------------------------------------
# Mode 1: Keep only Text and Vectors  (strip raster images only)
# ---------------------------------------------------------------------------

def keep_text_and_vectors(path: str | Path, output_dir: str | None = None,
                          progress=None) -> TextModeResult:
    """Delete every image XObject from every page's resources; leave text,
    vector paths, fonts, and annotations untouched. Then run the same
    structure rewrite as the normal pipeline to garbage-collect the now-
    unreferenced image objects."""
    import pikepdf
    from pikepdf import Name

    t0 = time.perf_counter()
    src = Path(path)
    res = TextModeResult(source=str(src), ok=False)
    try:
        v = validate_pdf(src)
        if not v.ok:
            raise ValueError(v.reason)
        res.in_bytes = src.stat().st_size

        if progress:
            progress("removing images...")
        pdf = pikepdf.open(src)
        try:
            res.pages = len(pdf.pages)
            removed = 0
            for page in pdf.pages:
                xobjs = page.obj.get("/Resources", {}).get("/XObject", None)
                if xobjs is None:
                    continue
                for name in list(xobjs.keys()):
                    try:
                        ref = xobjs[name]
                        if ref.get("/Subtype", None) == Name("/Image"):
                            del xobjs[name]
                            removed += 1
                    except Exception:
                        continue

            if progress:
                progress("rewriting structure...")
            buf = io.BytesIO()
            pdf.save(buf, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                     compress_streams=True, recompress_flate=True)
            data = buf.getvalue()
        finally:
            pdf.close()

        out = _output_path(src, "_text_vectors", output_dir)
        out.write_bytes(data)
        _verify(out)

        res.ok = True
        res.output = str(out)
        res.out_bytes = len(data)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    res.seconds = time.perf_counter() - t0
    return res


# ---------------------------------------------------------------------------
# Mode 2: Keep only Text  (full extract + redraw, base-14 fonts only)
# ---------------------------------------------------------------------------

def keep_text_only(path: str | Path, output_dir: str | None = None,
                   progress=None) -> TextModeResult:
    """Rebuild the PDF from nothing but its text. Every page becomes a
    blank page of the same size, with text redrawn at the original
    positions/sizes using one of the 14 standard fonts. No images, no
    vector art, no annotations, no forms, no embedded fonts, no metadata -
    only text survives."""
    import pikepdf
    from pikepdf import Name
    import pypdfium2 as pdfium

    t0 = time.perf_counter()
    src = Path(path)
    res = TextModeResult(source=str(src), ok=False)
    try:
        v = validate_pdf(src)
        if not v.ok:
            raise ValueError(v.reason)
        res.in_bytes = src.stat().st_size

        doc = pdfium.PdfDocument(str(src))
        try:
            n_pages = len(doc)
            res.pages = n_pages

            out_pdf = pikepdf.new()
            fonts_used: dict[str, pikepdf.Object] = {}
            total_chars = 0
            any_substituted = False

            for pi in range(n_pages):
                if progress:
                    progress(f"extracting text: page {pi+1}/{n_pages}...")
                page = doc[pi]
                w, h = page.get_size()
                tp = page.get_textpage()
                runs = _extract_runs(tp, h)
                tp.close()
                page.close()

                out_page = out_pdf.add_blank_page(page_size=(w, h))
                res_fonts = pikepdf.Dictionary()
                ops = [b"BT"]
                cur_font = None
                cur_size = None
                for run in runs:
                    if run.font not in fonts_used:
                        fonts_used[run.font] = out_pdf.make_indirect(pikepdf.Dictionary(
                            Type=Name("/Font"), Subtype=Name("/Type1"),
                            BaseFont=pikepdf.Name("/" + run.font),
                        ))
                    fkey = "F" + str(list(fonts_used.keys()).index(run.font))
                    res_fonts[Name("/" + fkey)] = fonts_used[run.font]
                    if cur_font != fkey or cur_size != run.size:
                        ops.append(f"/{fkey} {run.size:.2f} Tf".encode())
                        cur_font, cur_size = fkey, run.size
                    ops.append(f"1 0 0 1 {run.x:.2f} {run.y:.2f} Tm".encode())
                    escaped, substituted = _pdf_escape(run.text)
                    any_substituted = any_substituted or substituted
                    ops.append(b"(" + escaped + b") Tj")
                    total_chars += len(run.text)
                ops.append(b"ET")
                content = b"\n".join(ops)

                out_page.obj["/Resources"] = pikepdf.Dictionary(Font=res_fonts)
                out_page.obj["/Contents"] = out_pdf.make_indirect(
                    pikepdf.Stream(out_pdf, content))

            if progress:
                progress("finalizing...")
            buf = io.BytesIO()
            out_pdf.save(buf, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                        compress_streams=True)
            data = buf.getvalue()
            out_pdf.close()
        finally:
            doc.close()

        out = _output_path(src, "_text_only", output_dir)
        out.write_bytes(data)
        _verify(out)

        res.ok = True
        res.output = str(out)
        res.out_bytes = len(data)
        res.chars_kept = total_chars
        res.non_latin_detected = any_substituted
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    res.seconds = time.perf_counter() - t0
    return res


def _verify(path: Path) -> None:
    import pikepdf
    with pikepdf.open(path) as pdf:
        if len(pdf.pages) == 0:
            raise ValueError("output PDF has no pages")
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(path))
        try:
            p = doc[0]
            p.render(scale=0.2).to_pil()
            p.close()
        finally:
            doc.close()
    except ImportError:
        pass
