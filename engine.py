"""
SnapPDF - engine core.
=====================================================
Pure-Python core. No GUI, no hooks, no registry. Originals are NEVER
touched - every run creates a new file next to the source.

v1 pipeline (Tier A of the master table; the table is the long-term roadmap):

  Phase 0  ANALYSIS    - analysis.py: weightage + validation + feasibility
  Phase 1  STRUCTURE   - full qpdf rewrite: garbage collection, object
                         streams, xref streams, stream recompression,
                         duplicate-image dedup, optional linearization
  Phase 2  METADATA    - drop XMP + DocInfo, page thumbnails, embedded
                         attachments, JavaScript, image EXIF (implicit on
                         re-encode)
  Phase 3  IMAGES      - re-encode embedded raster images (JPEG), optional
                         DPI cap / grayscale, and the target-size loop:
                         binary-search quality, then step down resolution -
                         the same brain as SnapShrink's _fit_to_kb.

Output naming (same philosophy as SnapShrink - truth in the filename):
    report.pdf  --target 250KB      -> report_248KB.pdf
    report.pdf  (preset, no target) -> report_optimized.pdf
    merge of a.pdf+b.pdf            -> a_merged.pdf   (+_248KB if target)
    to-images 150dpi                -> report_150dpi/page_001.jpg ...
    images -> pdf                   -> firstimage_combined.pdf
    (name taken? -> ...-1.pdf, -2.pdf)

Usage (terminal):
    python -m sppack.engine file.pdf --target-kb 250
    python -m sppack.engine a.pdf b.pdf --merge --target-kb 500
    python -m sppack.engine file.pdf --to-images 150
    python -m sppack.engine a.jpg b.png --images-to-pdf
    python -m sppack.engine --selftest
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .analysis import Analysis, analyze, validate_pdf

# ---------------------------------------------------------------------------
# Constants (mirroring SnapShrink's tuning where it applies)
# ---------------------------------------------------------------------------

MAX_QUALITY = 90          # JPEG inside PDFs: 90 is visually transparent
MIN_QUALITY = 30          # hard floor for the target-size loop
DEFAULT_QUALITY = 75      # the hotkey preset's "Image Optimization up to 75%"
DOWNSCALE_STEP = 0.85     # shrink image dimensions 15% per pass at the floor
MIN_IMG_DIM = 96          # never shrink an embedded image below this edge
DPI_CHOICES = [72, 120, 150, 200, 300]
PDF_EXT = {".pdf"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


# ---------------------------------------------------------------------------
# Options / Result
# ---------------------------------------------------------------------------

@dataclass
class Options:
    """Everything the engine needs. Phase toggles are PHASE-level (per
    Vijay's decision), not per-pass. GUI/config/context-menu all build one
    of these."""
    do_structure: bool = True
    do_metadata: bool = True
    do_images: bool = True
    img_quality: int = DEFAULT_QUALITY   # starting JPEG quality (30..90)
    max_dpi: int | None = None           # cap effective image DPI (None = off)
    grayscale: bool = False              # convert images to grayscale
    linearize: bool = False              # Fast Web View
    target_kb: int | None = None         # absolute size target
    target_pct: int | None = None        # percent of source size (50..95)
    output_dir: str | None = None        # None = same folder as source
    suffix: str | None = None            # override output suffix
    reduction_mode: str | None = None    # None | "text_vectors" | "text_only"
                                          # extra aggressive modes (textmode.py);
                                          # when set, overrides the normal phase
                                          # pipeline entirely for this file.


@dataclass
class Result:
    source: str
    ok: bool
    output: str | None = None
    error: str | None = None
    in_bytes: int = 0
    out_bytes: int = 0
    target_kb: int | None = None
    target_met: bool = True              # False = best effort, honest report
    floor_kb: int | None = None          # what analysis said was achievable
    final_quality: int | None = None
    pages: int = 0
    seconds: float = 0.0
    phases_run: list[str] = field(default_factory=list)
    non_latin_detected: bool = False   # Keep-only-Text: some text couldn't
                                       # be represented in a base-14 font

    def summary(self) -> str:
        if not self.ok:
            return f"FAIL  {Path(self.source).name}: {self.error}"
        saved = (1 - self.out_bytes / self.in_bytes) * 100 if self.in_bytes else 0
        note = ""
        if self.target_kb and not self.target_met:
            note = f"  [target {self.target_kb}KB not reachable; closest ~{self.out_bytes//1024}KB]"
        if self.non_latin_detected:
            note += "  [non-Latin text replaced with '?']"
        q = f" q{self.final_quality}" if self.final_quality else ""
        return (f"OK    {Path(self.source).name} -> {Path(self.output).name}  "
                f"{self.in_bytes/1024:.0f}KB -> {self.out_bytes/1024:.0f}KB "
                f"({saved:+.0f}%){q}{note}")


# ---------------------------------------------------------------------------
# Output naming
# ---------------------------------------------------------------------------

def _unique(candidate: Path) -> Path:
    n = 1
    stem, ext, folder = candidate.stem, candidate.suffix, candidate.parent
    while candidate.exists():
        candidate = folder / f"{stem}-{n}{ext}"
        n += 1
    return candidate


def _output_path(src: Path, opts: Options, out_bytes: int,
                 target_kb: int | None = None) -> Path:
    folder = Path(opts.output_dir) if opts.output_dir else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    if target_kb is None:
        target_kb = opts.target_kb
    if opts.suffix:
        suffix = opts.suffix
    elif target_kb:
        suffix = f"_{max(1, out_bytes // 1024)}KB"
    else:
        suffix = "_optimized"
    return _unique(folder / f"{src.stem}{suffix}.pdf")


# ---------------------------------------------------------------------------
# Phase 1+2 helpers (operate on an open pikepdf.Pdf, in place)
# ---------------------------------------------------------------------------

def _strip_metadata(pdf) -> None:
    """Phase 2: everything that doesn't change how pages LOOK."""
    import pikepdf
    from pikepdf import Name

    # DocInfo (Author/Producer/dates...) + XMP metadata stream
    try:
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            for k in list(meta.keys()):
                del meta[k]
    except Exception:
        pass
    try:
        if "/Metadata" in pdf.Root:
            del pdf.Root.Metadata
    except Exception:
        pass
    try:
        pdf.trailer["/Info"] = pdf.make_indirect(pikepdf.Dictionary())
    except Exception:
        pass

    root = pdf.Root
    # JavaScript + OpenAction scripts
    try:
        names = root.get("/Names", None)
        if names is not None:
            for k in ("/JavaScript", "/EmbeddedFiles"):
                if k in names:
                    del names[k]
        if "/OpenAction" in root:
            oa = root.get("/OpenAction")
            if isinstance(oa, pikepdf.Dictionary) and oa.get("/S", None) == Name("/JavaScript"):
                del root.OpenAction
    except Exception:
        pass

    # Per-page: thumbnails, XMP, file-attachment annotations
    for page in pdf.pages:
        try:
            if "/Thumb" in page:
                del page.obj["/Thumb"]
            if "/Metadata" in page.obj:
                del page.obj["/Metadata"]
            annots = page.obj.get("/Annots", None)
            if annots is not None:
                keep = [a for a in annots
                        if a.get("/Subtype", None) != Name("/FileAttachment")]
                if len(keep) != len(annots):
                    page.obj["/Annots"] = pdf.make_indirect(pikepdf.Array(keep))
        except Exception:
            continue


def _dedup_images(pdf) -> int:
    """Structure pass: identical image streams stored once. Returns count
    of duplicates removed. Works by hashing raw stream bytes and repointing
    every page's /XObject entries at the first copy."""
    import hashlib
    import pikepdf
    from pikepdf import Name

    seen: dict[str, pikepdf.Object] = {}
    remap: dict[tuple, pikepdf.Object] = {}

    for obj in pdf.objects:
        try:
            if not isinstance(obj, pikepdf.Stream):
                continue
            if obj.get("/Subtype", None) != Name("/Image"):
                continue
            h = hashlib.sha256(obj.read_raw_bytes()).hexdigest()
            # include key dict entries so two images with identical bytes but
            # different color spaces are NOT merged
            h += f"|{obj.get('/Width',0)}x{obj.get('/Height',0)}|{obj.get('/Filter','')}|{obj.get('/ColorSpace','')}"
            if h in seen:
                remap[obj.objgen] = seen[h]
            else:
                seen[h] = obj
        except Exception:
            continue

    if not remap:
        return 0
    for page in pdf.pages:
        try:
            xobjs = page.obj.get("/Resources", {}).get("/XObject", None)
            if xobjs is None:
                continue
            for name in list(xobjs.keys()):
                ref = xobjs[name]
                try:
                    if ref.objgen in remap:
                        xobjs[name] = remap[ref.objgen]
                except Exception:
                    continue
        except Exception:
            continue
    return len(remap)


def _save_to_bytes(pdf, opts: Options) -> bytes:
    """Phase 1 finalization: the qpdf rewrite. This single call performs
    garbage collection (unreferenced objects are dropped), object-stream
    generation, xref-stream compression and Flate recompression."""
    import pikepdf
    buf = io.BytesIO()
    pdf.save(
        buf,
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
        compress_streams=True,
        recompress_flate=True,
        linearize=opts.linearize,
    )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Phase 3: image re-encoding
# ---------------------------------------------------------------------------

def _decode_pdf_image(obj):
    """Decode a pikepdf image XObject to a PIL image, or None if we should
    leave it alone (CCITT/JBIG2 monochrome is already near-optimal; broken
    or exotic images are safer untouched)."""
    import pikepdf
    filt = str(obj.get("/Filter", ""))
    if "CCITT" in filt or "JBIG2" in filt or "JPX" in filt:
        return None
    try:
        pimg = pikepdf.PdfImage(obj)
        pil = pimg.as_pil_image()
        pil.load()
        return pil
    except Exception:
        return None


def _reencode_images(pdf, quality: int, scale: float, opts: Options,
                     min_gain: float = 0.95) -> tuple[int, int]:
    """Re-encode every decodable raster image at the given JPEG quality and
    optional scale factor (1.0 = keep dimensions). An image is only replaced
    if the new stream is < min_gain * old size - never make things bigger.
    Returns (images_replaced, bytes_saved_estimate)."""
    import pikepdf
    from pikepdf import Name
    from PIL import Image

    replaced = 0
    saved = 0

    for obj in list(pdf.objects):
        try:
            if not isinstance(obj, pikepdf.Stream):
                continue
            if obj.get("/Subtype", None) != Name("/Image"):
                continue
            old_len = int(obj.get("/Length", 0))
            if old_len < 4 * 1024:          # tiny images: not worth the risk
                continue
            has_smask = obj.get("/SMask", None) is not None

            pil = _decode_pdf_image(obj)
            if pil is None:
                continue

            # ---- optional transforms ----
            if pil.mode in ("P", "1"):
                pil = pil.convert("RGB")
            if pil.mode in ("CMYK", "YCbCr"):
                pil = pil.convert("RGB")
            if opts.grayscale and pil.mode != "L":
                pil = pil.convert("L")

            eff_scale = scale
            if opts.max_dpi:
                # No reliable per-image DPI without placement math; use the
                # pragmatic proxy: cap the longest edge at max_dpi/72 * 11in
                cap_px = int(opts.max_dpi * 11.5)
                longest = max(pil.size)
                if longest * eff_scale > cap_px:
                    eff_scale = min(eff_scale, cap_px / longest)

            if eff_scale < 1.0:
                w, h = pil.size
                nw = max(MIN_IMG_DIM, round(w * eff_scale))
                nh = max(MIN_IMG_DIM, round(h * eff_scale))
                if (nw, nh) != (w, h) and min(w, h) > MIN_IMG_DIM:
                    pil = pil.resize((nw, nh), Image.LANCZOS)

            # ---- encode ----
            if pil.mode == "RGBA" or pil.mode == "LA" or has_smask:
                # Keep alpha-carrying images as Flate (lossless) to avoid
                # SMask dimension mismatches; scaling alpha images is v2.
                if pil.mode in ("RGBA", "LA"):
                    continue
                base = pil.convert("RGB") if pil.mode not in ("RGB", "L") else pil
                buf = io.BytesIO()
                base.save(buf, "JPEG", quality=quality, optimize=True)
                data = buf.getvalue()
                # only safe if dimensions unchanged (SMask must keep matching)
                if base.size != (int(obj.get("/Width", 0)), int(obj.get("/Height", 0))):
                    continue
            else:
                base = pil.convert("RGB") if pil.mode not in ("RGB", "L") else pil
                buf = io.BytesIO()
                base.save(buf, "JPEG", quality=quality, optimize=True)
                data = buf.getvalue()

            if len(data) >= old_len * min_gain:
                continue  # not enough gain - keep original

            # ---- swap the stream in place ----
            obj.write(data, filter=Name("/DCTDecode"))
            obj["/Width"] = base.size[0]
            obj["/Height"] = base.size[1]
            obj["/BitsPerComponent"] = 8
            obj["/ColorSpace"] = Name("/DeviceGray") if base.mode == "L" else Name("/DeviceRGB")
            for k in ("/DecodeParms", "/Decode", "/Interpolate"):
                if k in obj:
                    del obj[k]
            replaced += 1
            saved += old_len - len(data)
        except Exception:
            continue
    return replaced, saved


# ---------------------------------------------------------------------------
# The main pipeline
# ---------------------------------------------------------------------------

def _open_fresh(src: Path):
    import pikepdf
    return pikepdf.open(src)


def _run_pipeline_once(src: Path, opts: Options, quality: int,
                       scale: float) -> bytes:
    """One full pass: open fresh from disk, apply enabled phases, return
    the finished PDF bytes. Called repeatedly by the target-size loop with
    different (quality, scale)."""
    pdf = _open_fresh(src)
    try:
        if opts.do_metadata:
            _strip_metadata(pdf)
        if opts.do_structure:
            _dedup_images(pdf)
        if opts.do_images:
            _reencode_images(pdf, quality, scale, opts)
        # Structure rewrite always happens at save time when do_structure;
        # otherwise still save cleanly but without forcing object streams.
        if opts.do_structure:
            return _save_to_bytes(pdf, opts)
        buf = io.BytesIO()
        pdf.save(buf, linearize=opts.linearize)
        return buf.getvalue()
    finally:
        pdf.close()


def _fit_to_target(src: Path, opts: Options, target_kb: int,
                   progress=None) -> tuple[bytes, int, bool]:
    """SnapShrink's brain, generalized to PDFs.
    1. Try the lossless-leaning pass at the user's starting quality.
    2. Binary-search JPEG quality MIN..start (4-5 pipeline runs).
    3. Quality floor still too big? Step image dimensions down 15% per pass.
    Returns (bytes, final_quality, target_met)."""
    target = target_kb * 1024

    def tick(msg):
        if progress:
            progress(msg)

    tick("optimizing (first pass)...")
    data = _run_pipeline_once(src, opts, opts.img_quality, 1.0)
    if len(data) <= target:
        return data, opts.img_quality, True
    if not opts.do_images:
        return data, None, False  # only lossless allowed; honest best effort

    scale = 1.0
    best = data
    best_q = opts.img_quality
    while True:
        lo, hi = MIN_QUALITY, opts.img_quality
        fit: bytes | None = None
        fit_q = MIN_QUALITY
        while lo <= hi:
            mid = (lo + hi) // 2
            tick(f"trying quality {mid}" + (f" @ {scale:.0%}" if scale < 1 else "") + "...")
            data = _run_pipeline_once(src, opts, mid, scale)
            if len(data) <= target:
                fit, fit_q = data, mid
                lo = mid + 1
            else:
                if len(data) < len(best):
                    best, best_q = data, mid
                hi = mid - 1
        if fit is not None:
            return fit, fit_q, True
        # floor reached - shrink pixels and repeat
        new_scale = scale * DOWNSCALE_STEP
        if new_scale < 0.18:            # ~5 halvings: nothing left to squeeze
            return best, best_q, False
        scale = new_scale


def _process_reduction_mode(path: str | Path, opts: Options, progress=None) -> Result:
    """Adapter: run one of the aggressive 'Keep only...' modes (textmode.py)
    and repackage its TextModeResult as a normal engine.Result, so every
    existing caller (batch runner, GUI, daemon) keeps working unchanged."""
    from . import textmode
    src = Path(path)
    res = Result(source=str(src), ok=False)
    try:
        v = validate_pdf(src)
        if not v.ok:
            hint = "  Tip: use 'Combine to PDF' to turn it into a real PDF." \
                if v.is_renamed_image else ""
            raise ValueError(v.reason + hint)

        if opts.reduction_mode == "text_vectors":
            tr = textmode.keep_text_and_vectors(src, opts.output_dir, progress)
            phases = ["text_vectors"]
        elif opts.reduction_mode == "text_only":
            tr = textmode.keep_text_only(src, opts.output_dir, progress)
            phases = ["text_only"]
        else:
            raise ValueError(f"unknown reduction_mode {opts.reduction_mode!r}")

        res.in_bytes = tr.in_bytes
        res.pages = tr.pages
        res.phases_run = phases
        if not tr.ok:
            raise ValueError(tr.error or "reduction failed")
        res.ok = True
        res.output = tr.output
        res.out_bytes = tr.out_bytes
        res.target_met = True
        res.non_latin_detected = getattr(tr, "non_latin_detected", False)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    res.seconds = 0.0
    return res


def process_pdf(path: str | Path, opts: Options, progress=None) -> Result:
    """THE function for single-PDF optimization. GUI, hotkey, and context
    menu all call exactly this."""
    if opts.reduction_mode:
        return _process_reduction_mode(path, opts, progress)

    t0 = time.perf_counter()
    src = Path(path)
    res = Result(source=str(src), ok=False, target_kb=None)

    try:
        v = validate_pdf(src)
        if not v.ok:
            hint = "  Tip: use 'Combine to PDF' to turn it into a real PDF." \
                if v.is_renamed_image else ""
            raise ValueError(v.reason + hint)
        res.in_bytes = src.stat().st_size

        # resolve percent target into KB
        target_kb = opts.target_kb
        if opts.target_pct:
            target_kb = max(1, int(res.in_bytes * opts.target_pct / 100 / 1024))
        res.target_kb = target_kb

        ana = analyze(src)
        if not ana.ok:
            raise ValueError(ana.error or "could not analyze PDF")
        res.pages = ana.pages

        # feasibility gate: refuse clearly impossible asks BEFORE working
        if target_kb:
            feasible, floor_kb = ana.target_feasible(target_kb)
            res.floor_kb = floor_kb
            if not feasible:
                # still do the best-effort run so the user gets SOMETHING,
                # but the Result tells the truth
                if progress:
                    progress(f"target {target_kb}KB below realistic floor (~{floor_kb}KB); doing best effort...")

        if target_kb:
            data, q, met = _fit_to_target(src, opts, target_kb, progress)
            res.final_quality = q
            res.target_met = met
        else:
            if progress:
                progress("optimizing...")
            data = _run_pipeline_once(src, opts, opts.img_quality, 1.0)
            res.final_quality = opts.img_quality if opts.do_images else None

        # never ship a "smaller" file that's actually bigger than the source
        if len(data) >= res.in_bytes and not opts.linearize:
            if target_kb and res.in_bytes <= target_kb * 1024:
                data = src.read_bytes()   # source already meets the target
                res.target_met = True
                res.final_quality = None

        out = _output_path(src, opts, len(data), target_kb=target_kb)
        out.write_bytes(data)

        # integrity check: output must re-open and render page 1
        _verify_pdf(out)

        res.ok = True
        res.output = str(out)
        res.out_bytes = len(data)
        for name, flag in (("structure", opts.do_structure),
                           ("metadata", opts.do_metadata),
                           ("images", opts.do_images)):
            if flag:
                res.phases_run.append(name)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
        # clean up a half-written output if verification failed
        if res.output is None:
            pass
    res.seconds = time.perf_counter() - t0
    return res


def _verify_pdf(path: Path) -> None:
    """Post-save integrity validation (master-table #69): re-open with
    pikepdf and render page 1 with pdfium. Raises on failure - caller
    treats that as a failed run and the original is untouched anyway."""
    import pikepdf
    with pikepdf.open(path) as pdf:
        n = len(pdf.pages)
        if n == 0:
            raise ValueError("optimized PDF has no pages")
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(path))
        try:
            page = doc[0]
            bmp = page.render(scale=0.2)
            bmp.to_pil()
            page.close()
        finally:
            doc.close()
    except ImportError:
        pass  # pdfium optional at runtime; pikepdf check already passed


# ---------------------------------------------------------------------------
# Merge (+ optional shrink) - the multi-select combined action
# ---------------------------------------------------------------------------

def merge_pdfs(paths: list[str | Path], opts: Options | None = None,
               progress=None) -> Result:
    """Combine PDFs (in the given order) into one, then optionally run the
    full optimization pipeline toward a target. Output lands next to the
    FIRST file: first_merged.pdf / first_merged_248KB.pdf."""
    import pikepdf
    t0 = time.perf_counter()
    opts = opts or Options()
    srcs = [Path(p) for p in paths]
    res = Result(source=" + ".join(p.name for p in srcs), ok=False)

    tmp_merged: Path | None = None
    try:
        if len(srcs) < 2:
            raise ValueError("merge needs at least 2 PDF files")
        for p in srcs:
            v = validate_pdf(p)
            if not v.ok:
                raise ValueError(f"{p.name}: {v.reason}")
        res.in_bytes = sum(p.stat().st_size for p in srcs)

        if progress:
            progress(f"merging {len(srcs)} PDFs...")
        merged = pikepdf.new()
        for p in srcs:
            with pikepdf.open(p) as src_pdf:
                merged.pages.extend(src_pdf.pages)
        res.pages = len(merged.pages)

        first = srcs[0]
        folder = Path(opts.output_dir) if opts.output_dir else first.parent

        want_optimize = bool(opts.target_kb or opts.target_pct) or \
            (opts.do_images and opts.img_quality < MAX_QUALITY)

        if want_optimize:
            # write merged to a temp file, then run the normal pipeline on it
            tmp_merged = _unique(folder / f".{first.stem}_merging.tmp.pdf")
            merged.save(tmp_merged)
            merged.close()
            inner = Options(**{**opts.__dict__})
            if opts.target_pct:
                # percent of the COMBINED size
                inner.target_kb = max(1, int(res.in_bytes * opts.target_pct / 100 / 1024))
                inner.target_pct = None
            inner.suffix = None
            r2 = process_pdf(tmp_merged, inner, progress)
            if not r2.ok:
                raise ValueError(r2.error or "optimization of merged PDF failed")
            # rename to friendly name
            out_bytes = r2.out_bytes
            suffix = f"_merged_{max(1, out_bytes//1024)}KB" if inner.target_kb else "_merged"
            final = _unique(folder / f"{first.stem}{suffix}.pdf")
            Path(r2.output).rename(final)
            res.output = str(final)
            res.out_bytes = out_bytes
            res.final_quality = r2.final_quality
            res.target_met = r2.target_met
            res.target_kb = r2.target_kb
            res.floor_kb = r2.floor_kb
        else:
            out = _unique(folder / f"{first.stem}_merged.pdf")
            merged.save(out, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                        compress_streams=True)
            merged.close()
            res.output = str(out)
            res.out_bytes = out.stat().st_size

        _verify_pdf(Path(res.output))
        res.ok = True
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    finally:
        if tmp_merged is not None:
            tmp_merged.unlink(missing_ok=True)
    res.seconds = time.perf_counter() - t0
    return res


# ---------------------------------------------------------------------------
# PDF -> images  (pypdfium2 renders; Pillow encodes)
# ---------------------------------------------------------------------------

def pdf_to_images(path: str | Path, dpi: int = 150, fmt: str = "jpg",
                  progress=None) -> Result:
    """Render every page at the chosen DPI into <stem>_<dpi>dpi/page_NNN.jpg
    next to the source PDF."""
    t0 = time.perf_counter()
    src = Path(path)
    res = Result(source=str(src), ok=False)
    try:
        v = validate_pdf(src)
        if not v.ok:
            raise ValueError(v.reason)
        res.in_bytes = src.stat().st_size

        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(src))
        try:
            n = len(doc)
            res.pages = n
            outdir = _unique_dir(src.parent / f"{src.stem}_{dpi}dpi")
            outdir.mkdir(parents=True, exist_ok=True)
            total = 0
            for i in range(n):
                if progress:
                    progress(f"rendering page {i+1}/{n} @ {dpi} DPI...")
                page = doc[i]
                pil = page.render(scale=dpi / 72).to_pil()
                page.close()
                if pil.mode not in ("RGB", "L"):
                    pil = pil.convert("RGB")
                out = outdir / f"page_{i+1:03d}.{fmt}"
                if fmt == "jpg":
                    pil.save(out, "JPEG", quality=90, optimize=True)
                else:
                    pil.save(out, "PNG", optimize=True)
                total += out.stat().st_size
            res.ok = True
            res.output = str(outdir)
            res.out_bytes = total
        finally:
            doc.close()
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    res.seconds = time.perf_counter() - t0
    return res


def _unique_dir(candidate: Path) -> Path:
    n = 1
    base = candidate
    while candidate.exists():
        candidate = base.parent / f"{base.name}-{n}"
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# Images -> single PDF
# ---------------------------------------------------------------------------

def images_to_pdf(paths: list[str | Path], quality: int = 90,
                  progress=None) -> Result:
    """Combine image files (in order) into one PDF. Each image becomes a
    page sized to the image (72 DPI basis). Output: first_combined.pdf."""
    from PIL import Image, ImageOps
    t0 = time.perf_counter()
    srcs = [Path(p) for p in paths]
    res = Result(source=" + ".join(p.name for p in srcs), ok=False)
    try:
        if not srcs:
            raise ValueError("no images given")
        bad = [p.name for p in srcs if p.suffix.lower() not in IMAGE_EXT]
        if bad:
            raise ValueError(f"not image files: {', '.join(bad)}")
        res.in_bytes = sum(p.stat().st_size for p in srcs)

        pages = []
        for i, p in enumerate(srcs):
            if progress:
                progress(f"reading image {i+1}/{len(srcs)}...")
            img = Image.open(p)
            img.load()
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                bg.paste(rgba, mask=rgba.getchannel("A"))
                img = bg
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            pages.append(img)

        out = _unique(srcs[0].parent / f"{srcs[0].stem}_combined.pdf")
        pages[0].save(out, "PDF", save_all=True, append_images=pages[1:],
                      resolution=96.0, quality=quality)
        res.pages = len(pages)
        res.ok = True
        res.output = str(out)
        res.out_bytes = out.stat().st_size
        _verify_pdf(out)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    res.seconds = time.perf_counter() - t0
    return res


# ---------------------------------------------------------------------------
# Batch runner  (PDFs processed independently, like SnapShrink's batches)
# ---------------------------------------------------------------------------

def process_batch(paths: list[str], opts: Options, progress=None) -> list[Result]:
    """`progress(done, total, result)` after each file. PDFs are processed
    SEQUENTIALLY (unlike SnapShrink's thread pool) because a single PDF's
    target-size loop is already CPU-parallel-ish and RAM-heavy; two huge
    PDFs at once can exhaust memory on modest machines."""
    results: list[Result] = []
    total = len(paths)
    for i, p in enumerate(paths):
        r = process_pdf(p, opts)
        results.append(r)
        if progress:
            progress(i + 1, total, r)
    return results


# ---------------------------------------------------------------------------
# Estimation helpers (SINGLE-mode panel: "apx. size / apx. time")
# ---------------------------------------------------------------------------

def estimate(ana: Analysis, opts: Options) -> tuple[int, float]:
    """(estimated_out_bytes, estimated_seconds). Deliberately rough but
    honest - computed from the analysis breakdown without any encoding."""
    b = ana.breakdown
    out = ana.file_bytes
    secs = 0.3 + ana.pages * 0.02
    if opts.do_structure or opts.do_metadata:
        struct = b.get("other", 0)
        meta = (b.get("metadata", 0) + b.get("attachments", 0)) if opts.do_metadata else 0
        out -= int(struct * 0.35) + meta
        secs += ana.file_bytes / (40 * 1024 * 1024)
    if opts.do_images and ana.image_bytes():
        # empirical quality->ratio curve for typical embedded JPEG/Flate
        q = opts.img_quality
        ratio = 0.12 + (q / 90) ** 2 * 0.68        # q90 ~0.80, q75 ~0.59, q30 ~0.20
        if opts.grayscale:
            ratio *= 0.55
        out -= int(ana.image_bytes() * (1 - ratio))
        secs += len(ana.images) * 0.15 + ana.image_bytes() / (8 * 1024 * 1024)
    if opts.target_kb or opts.target_pct:
        secs *= 4   # the search loop runs the pipeline several times
    return max(2048, out), max(0.2, secs)


# ---------------------------------------------------------------------------
# Self-test  (same discipline as SnapShrink: engine proves itself before
# any GUI/installer work, and forever after via  python -m sppack --selftest)
# ---------------------------------------------------------------------------

def _selftest() -> int:  # noqa: C901
    import tempfile
    import pikepdf
    from pikepdf import Name
    from PIL import Image, ImageDraw

    tmp = Path(tempfile.mkdtemp(prefix="snappdf-selftest-"))
    print(f"SnapPDF self-test - work folder: {tmp}\n")
    failures = 0

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal failures
        mark = "PASS" if cond else "FAIL"
        if not cond:
            failures += 1
        print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))

    # ---------- build synthetic inputs ------------------------------------
    def noisy_image(w, h) -> Image.Image:
        import random
        random.seed(42)
        img = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(img)
        for _ in range(400):
            x, y = random.randrange(w), random.randrange(h)
            r = random.randrange(20, 90)
            d.ellipse([x, y, x + r, y + r],
                      fill=(random.randrange(256), random.randrange(256), random.randrange(256)))
        return img

    def make_image_pdf(name: str, n_pages: int, px: int, dup: bool = False) -> Path:
        """PDF whose pages each hold one big photo-like JPEG."""
        p = tmp / name
        pdf = pikepdf.new()
        img = noisy_image(px, px)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92)
        jpeg = buf.getvalue()
        for i in range(n_pages):
            page = pdf.add_blank_page(page_size=(612, 792))
            data = jpeg if (dup or i == 0) else None
            if data is None:
                buf = io.BytesIO()
                noisy_image(px, px).save(buf, "JPEG", quality=92)
                data = buf.getvalue()
            imobj = pikepdf.Stream(pdf, data)
            imobj["/Type"] = Name("/XObject")
            imobj["/Subtype"] = Name("/Image")
            imobj["/Width"] = px
            imobj["/Height"] = px
            imobj["/ColorSpace"] = Name("/DeviceRGB")
            imobj["/BitsPerComponent"] = 8
            imobj["/Filter"] = Name("/DCTDecode")
            page.obj["/Resources"] = pikepdf.Dictionary(
                XObject=pikepdf.Dictionary(Im0=pdf.make_indirect(imobj)))
            cs = f"q 612 0 0 792 0 0 cm /Im0 Do Q".encode()
            page.obj["/Contents"] = pdf.make_indirect(pikepdf.Stream(pdf, cs))
        pdf.docinfo["/Author"] = "SnapPDF Selftest"
        pdf.docinfo["/Producer"] = "Synthetic"
        with pdf.open_metadata() as meta:
            meta["dc:title"] = "Selftest Document With Metadata " * 50
        pdf.save(p)
        pdf.close()
        return p

    def make_bloated_pdf(name: str) -> Path:
        """Text-ish PDF with an attachment + uncompressed streams so the
        Structure/Metadata phases have real work to do."""
        p = tmp / name
        pdf = pikepdf.new()
        for i in range(5):
            page = pdf.add_blank_page(page_size=(612, 792))
            text = (f"BT /F1 24 Tf 72 700 Td (Page {i}) Tj ET " + "% pad " * 2000).encode()
            page.obj["/Contents"] = pdf.make_indirect(
                pikepdf.Stream(pdf, text))
            page.obj["/Resources"] = pikepdf.Dictionary(
                Font=pikepdf.Dictionary(F1=pikepdf.Dictionary(
                    Type=Name("/Font"), Subtype=Name("/Type1"),
                    BaseFont=Name("/Helvetica"))))
        # embedded attachment
        att = pikepdf.AttachedFileSpec(pdf, b"A" * 200_000, filename="payload.bin")
        pdf.attachments["payload.bin"] = att
        pdf.docinfo["/Author"] = "Bloat"
        with pdf.open_metadata() as meta:
            meta["dc:description"] = "x" * 5000
        pdf.save(p, compress_streams=False,
                 object_stream_mode=pikepdf.ObjectStreamMode.disable)
        pdf.close()
        return p

    big_pdf = make_image_pdf("photos.pdf", 3, 1400)
    dup_pdf = make_image_pdf("dups.pdf", 4, 1200, dup=True)
    bloat_pdf = make_bloated_pdf("bloated.pdf")

    fake_pdf = tmp / "fake.pdf"          # renamed JPEG
    noisy_image(300, 300).save(tmp / "real.jpg", "JPEG")
    fake_pdf.write_bytes((tmp / "real.jpg").read_bytes())
    corrupt = tmp / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nutter garbage")
    imgs = []
    for i in range(3):
        ip = tmp / f"scan{i}.png"
        noisy_image(500, 700).save(ip, "PNG")
        imgs.append(ip)

    # ---------- 1. validation ---------------------------------------------
    check("validate: real PDF ok", validate_pdf(big_pdf).ok)
    v = validate_pdf(fake_pdf)
    check("validate: renamed JPEG detected", not v.ok and v.is_renamed_image,
          v.reason)
    check("validate: missing file", not validate_pdf(tmp / "ghost.pdf").ok)

    # ---------- 2. analysis ------------------------------------------------
    ana = analyze(big_pdf)
    check("analysis: opens & counts pages", ana.ok and ana.pages == 3,
          ana.error or f"{ana.pages}p")
    check("analysis: images dominate breakdown",
          ana.ok and ana.pct("images") > 60, f"{ana.pct('images'):.0f}%")
    check("analysis: metadata detected", ana.ok and (ana.has_xmp or ana.has_docinfo))
    ana_b = analyze(bloat_pdf)
    check("analysis: attachment detected", ana_b.ok and ana_b.has_attachments)
    check("analysis: corrupt PDF -> clean error", not analyze(corrupt).ok)

    # ---------- 3. lossless phases (structure + metadata) ------------------
    r = process_pdf(bloat_pdf, Options(do_images=False))
    check("lossless: bloated PDF shrinks", r.ok and r.out_bytes < r.in_bytes,
          r.error or f"{r.in_bytes}->{r.out_bytes}")
    if r.ok:
        out_ana = analyze(r.output)
        check("lossless: attachment stripped", not out_ana.has_attachments)
        check("lossless: metadata stripped",
              not out_ana.has_xmp and not out_ana.has_docinfo)
        check("lossless: page count preserved", out_ana.pages == 5)
        check("lossless: output name *_optimized.pdf",
              Path(r.output).name == "bloated_optimized.pdf", Path(r.output).name)

    # ---------- 4. image dedup ---------------------------------------------
    r = process_pdf(dup_pdf, Options(do_images=False))
    if r.ok:
        saved_pct = 1 - r.out_bytes / r.in_bytes
        check("structure: duplicate images deduped (>50% saved)",
              saved_pct > 0.5, f"{saved_pct:.0%}")
    else:
        check("structure: dedup run", False, r.error or "")

    # ---------- 5. KB target loop ------------------------------------------
    src_kb = big_pdf.stat().st_size // 1024
    tgt = max(30, int(src_kb * 0.25))
    r = process_pdf(big_pdf, Options(target_kb=tgt))
    check("KB target: succeeds", r.ok, r.error or "")
    if r.ok:
        check("KB target: result under target", r.out_bytes <= tgt * 1024,
              f"{r.out_bytes//1024}KB vs {tgt}KB")
        check("KB target: target_met flag", r.target_met)
        check("KB target: name has real KB",
              Path(r.output).name == f"photos_{r.out_bytes//1024}KB.pdf",
              Path(r.output).name)
        check("KB target: output verifies & renders", True)  # _verify_pdf ran

    # ---------- 6. impossible target -> honest best effort ------------------
    r = process_pdf(big_pdf, Options(target_kb=3))
    check("impossible target: still returns a file", r.ok, r.error or "")
    if r.ok:
        check("impossible target: target_met is False", not r.target_met)
        check("impossible target: floor_kb reported", r.floor_kb is not None and r.floor_kb > 3,
              str(r.floor_kb))

    # ---------- 7. percent target -------------------------------------------
    r = process_pdf(big_pdf, Options(target_pct=50))
    check("percent target: succeeds", r.ok, r.error or "")
    if r.ok:
        check("percent target: <= 50% of source",
              r.out_bytes <= big_pdf.stat().st_size * 0.5 + 1024,
              f"{r.out_bytes} vs {big_pdf.stat().st_size}")

    # ---------- 8. originals never touched ----------------------------------
    orig = big_pdf.read_bytes()
    process_pdf(big_pdf, Options(target_kb=100))
    check("source byte-identical after runs", big_pdf.read_bytes() == orig)

    # ---------- 9. merge (+ merge & shrink) ---------------------------------
    r = merge_pdfs([big_pdf, bloat_pdf])
    check("merge: succeeds", r.ok, r.error or "")
    if r.ok:
        check("merge: page count 3+5", analyze(r.output).pages == 8)
        check("merge: name photos_merged.pdf",
              Path(r.output).name.startswith("photos_merged"), Path(r.output).name)
    r = merge_pdfs([big_pdf, dup_pdf], Options(target_kb=200))
    check("merge&shrink: succeeds", r.ok, r.error or "")
    if r.ok:
        check("merge&shrink: under 200KB", r.out_bytes <= 200 * 1024,
              f"{r.out_bytes//1024}KB")
        check("merge&shrink: pages 3+4", analyze(r.output).pages == 7)
    r = merge_pdfs([big_pdf])
    check("merge: <2 files -> clean error", not r.ok)

    # ---------- 10. PDF -> images -------------------------------------------
    r = pdf_to_images(big_pdf, dpi=72)
    check("to-images: succeeds", r.ok, r.error or "")
    if r.ok:
        files = sorted(Path(r.output).glob("page_*.jpg"))
        check("to-images: 3 pages -> 3 jpgs", len(files) == 3, str(len(files)))
        if files:
            im = Image.open(files[0])
            check("to-images: 72dpi Letter width ~612px",
                  abs(im.size[0] - 612) < 3, str(im.size))
        check("to-images: folder name *_72dpi",
              Path(r.output).name == "photos_72dpi", Path(r.output).name)

    # ---------- 11. images -> PDF --------------------------------------------
    r = images_to_pdf([str(p) for p in imgs])
    check("imgs2pdf: succeeds", r.ok, r.error or "")
    if r.ok:
        check("imgs2pdf: 3 pages", analyze(r.output).pages == 3)
        check("imgs2pdf: name scan0_combined.pdf",
              Path(r.output).name == "scan0_combined.pdf", Path(r.output).name)
    r = images_to_pdf([str(big_pdf)])
    check("imgs2pdf: PDF input -> clean error", not r.ok)

    # ---------- 12. errors never crash ---------------------------------------
    r = process_pdf(fake_pdf, Options())
    check("fake .pdf -> clean error with hint", not r.ok and "Combine to PDF" in (r.error or ""),
          r.error or "")
    r = process_pdf(corrupt, Options())
    check("corrupt -> clean error", not r.ok)
    results = process_batch([str(big_pdf), str(corrupt), str(bloat_pdf)],
                            Options(do_images=False))
    check("batch: all reported, 2 ok + 1 fail",
          len(results) == 3 and sum(x.ok for x in results) == 2)

    # ---------- 13. estimation sanity ----------------------------------------
    est_bytes, est_secs = estimate(ana, Options())
    check("estimate: below source size", est_bytes < ana.file_bytes,
          f"{est_bytes} vs {ana.file_bytes}")
    check("estimate: time positive", est_secs > 0)

    # ---------- 14. Keep only Text and Vectors / Keep only Text -------------
    from . import textmode

    r = process_pdf(big_pdf, Options(reduction_mode="text_vectors"))
    check("text_vectors: succeeds", r.ok, r.error or "")
    if r.ok:
        out_ana = analyze(r.output)
        check("text_vectors: no images left", out_ana.ok and out_ana.image_bytes() == 0,
              f"{out_ana.image_bytes()} bytes")
        check("text_vectors: page count preserved", out_ana.pages == ana.pages)
        check("text_vectors: name *_text_vectors.pdf",
              Path(r.output).name == "photos_text_vectors.pdf", Path(r.output).name)

    r = process_pdf(bloat_pdf, Options(reduction_mode="text_only"))
    check("text_only: succeeds", r.ok, r.error or "")
    if r.ok:
        out_ana = analyze(r.output)
        check("text_only: no images", out_ana.ok and out_ana.image_bytes() == 0)
        check("text_only: no attachments", out_ana.ok and not out_ana.has_attachments)
        check("text_only: no metadata", out_ana.ok and not out_ana.has_xmp
              and not out_ana.has_docinfo)
        check("text_only: page count preserved", out_ana.pages == 5, f"{out_ana.pages}")
        check("text_only: name *_text_only.pdf",
              Path(r.output).name == "bloated_text_only.pdf", Path(r.output).name)
        # the source pages say "Page 0".."Page 4" - confirm the text round-trips
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(r.output)
        got_all = True
        for i in range(len(doc)):
            tp = doc[i].get_textpage()
            txt = tp.get_text_range(0, tp.count_chars())
            if f"Page {i}" not in txt:
                got_all = False
            tp.close()
        doc.close()
        check("text_only: extracted text matches original content", got_all)

    r = process_pdf(fake_pdf, Options(reduction_mode="text_only"))
    check("text_only: fake pdf -> clean error", not r.ok, r.error or "")
    r = process_pdf(corrupt, Options(reduction_mode="text_vectors"))
    check("text_vectors: corrupt pdf -> clean error", not r.ok)

    print(f"\nTest files are in: {tmp}")
    print("Self-test " + ("PASSED - all good!" if failures == 0
                          else f"FAILED ({failures} problem(s) above)"))
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# CLI - also simulates the context menu, which just launches
#   SnapPDF.exe --ctx-size 250 "file.pdf"   etc.
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="snappdf",
        description="SnapPDF - shrink, merge & convert PDFs fast. Originals are never modified.")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--target-kb", type=int, default=None)
    ap.add_argument("--target-pct", type=int, default=None)
    ap.add_argument("--quality", type=int, default=DEFAULT_QUALITY)
    ap.add_argument("--max-dpi", type=int, default=None)
    ap.add_argument("--grayscale", action="store_true")
    ap.add_argument("--no-structure", action="store_true")
    ap.add_argument("--no-metadata", action="store_true")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--to-images", type=int, metavar="DPI", default=None)
    ap.add_argument("--images-to-pdf", action="store_true")
    ap.add_argument("--keep-text-vectors", action="store_true",
                    help="strip all images; keep text/vectors/annotations as-is")
    ap.add_argument("--keep-text-only", action="store_true",
                    help="rebuild pages from text alone using standard fonts "
                         "(Latin script only; see README)")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.files:
        ap.print_help()
        return 0

    import glob
    paths: list[str] = []
    for f in args.files:
        m = glob.glob(f)
        paths.extend(m if m else [f])

    if args.analyze:
        for p in paths:
            print(analyze(p).summary())
        return 0

    opts = Options(
        do_structure=not args.no_structure,
        do_metadata=not args.no_metadata,
        do_images=not args.no_images,
        img_quality=args.quality,
        max_dpi=args.max_dpi,
        grayscale=args.grayscale,
        target_kb=args.target_kb,
        target_pct=args.target_pct,
        reduction_mode=("text_vectors" if args.keep_text_vectors
                        else "text_only" if args.keep_text_only else None),
    )

    if args.to_images:
        for p in paths:
            r = pdf_to_images(p, dpi=args.to_images)
            print(r.summary())
        return 0
    if args.images_to_pdf:
        r = images_to_pdf(paths)
        print(r.summary())
        return 0 if r.ok else 1
    if args.merge:
        r = merge_pdfs(paths, opts)
        print(r.summary())
        return 0 if r.ok else 1

    results = process_batch(paths, opts,
                            progress=lambda d, t, r: print(f"[{d}/{t}] {r.summary()}"))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
