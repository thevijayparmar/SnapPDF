"""
SnapPDF - Phase 1 of every run: the Analysis Engine.

Scans a PDF WITHOUT modifying it and answers three questions:
  1. Is this even a real, openable PDF?   (validate)
  2. Where are the bytes going?           (analyze -> per-category weightage)
  3. How small can it realistically get?  (feasibility floor for target sizes)

The GUI's SINGLE-mode "weightage panel" is rendered straight from an
Analysis object; the engine uses the same object to fail fast on
impossible targets (2 GB PDF -> 10 KB) before wasting the user's time.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Validation - cheap checks that run before pikepdf even opens the file
# ---------------------------------------------------------------------------

# Magic bytes of common formats people rename to .pdf by accident
_IMAGE_MAGICS = [
    (b"\xff\xd8\xff", "JPEG image"),
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"GIF87a", "GIF image"),
    (b"GIF89a", "GIF image"),
    (b"BM", "BMP image"),
    (b"II*\x00", "TIFF image"),
    (b"MM\x00*", "TIFF image"),
    (b"RIFF", "WebP/RIFF file"),
]


@dataclass
class Validation:
    ok: bool
    reason: str = ""            # human-readable explanation when not ok
    actual_kind: str = ""       # e.g. "JPEG image" for renamed files
    is_renamed_image: bool = False  # True -> offer "convert to PDF instead?"


def validate_pdf(path: str | Path) -> Validation:
    """Header-level sanity check. Does NOT guarantee the PDF parses -
    pikepdf does that later - but catches the classic 'xyz.jpg renamed
    to xyz.pdf' case instantly and with a friendly message."""
    p = Path(path)
    if not p.is_file():
        return Validation(False, "file does not exist")
    if p.stat().st_size == 0:
        return Validation(False, "file is empty (0 bytes)")
    try:
        head = p.open("rb").read(1024)
    except OSError as e:
        return Validation(False, f"cannot read file: {e}")

    # The spec allows junk before %PDF- as long as it's in the first 1024 bytes
    if b"%PDF-" in head:
        return Validation(True)

    for magic, kind in _IMAGE_MAGICS:
        if head.startswith(magic):
            return Validation(
                False,
                f"this is really a {kind} that was renamed to .pdf",
                actual_kind=kind, is_renamed_image=True,
            )
    return Validation(False, "not a PDF file (missing %PDF header)")


# ---------------------------------------------------------------------------
# 2. Weightage analysis - where do the bytes live?
# ---------------------------------------------------------------------------

# Category keys, in the order the GUI shows them. "other" is the remainder
# (xref, dictionaries, whitespace, structural glue) computed by subtraction.
CATEGORIES = [
    ("images",      "Images"),
    ("fonts",       "Fonts"),
    ("content",     "Page content (text & vectors)"),
    ("attachments", "Embedded attachments"),
    ("metadata",    "Metadata & thumbnails"),
    ("other",       "Structure & overhead"),
]


@dataclass
class ImageInfo:
    objgen: tuple[int, int]
    width: int
    height: int
    bytes: int
    filter: str = ""
    has_smask: bool = False


@dataclass
class Analysis:
    path: str
    ok: bool = False
    error: str | None = None
    file_bytes: int = 0
    pages: int = 0
    encrypted: bool = False
    # bytes per category (raw stream lengths; "other" = remainder)
    breakdown: dict[str, int] = field(default_factory=dict)
    images: list[ImageInfo] = field(default_factory=list)
    has_javascript: bool = False
    has_attachments: bool = False
    has_thumbnails: bool = False
    has_xmp: bool = False
    has_docinfo: bool = False

    # ---------------- derived helpers used by GUI + engine -----------------

    def pct(self, key: str) -> float:
        return 100.0 * self.breakdown.get(key, 0) / self.file_bytes if self.file_bytes else 0.0

    def image_bytes(self) -> int:
        return self.breakdown.get("images", 0)

    def non_image_bytes(self) -> int:
        return max(0, self.file_bytes - self.image_bytes())

    def floor_estimate_bytes(self) -> int:
        """The smallest size this PDF can *plausibly* reach with SnapPDF's
        v1 pipeline. Deliberately conservative-cheap (no encoding done):
          - non-image data typically compacts to ~55-100% after a rewrite
          - each raster image can rarely go below ~3 KB and ~2% of itself
        Used ONLY to refuse clearly impossible targets up front; the real
        loop still reports honest best-effort numbers."""
        non_img = int(self.non_image_bytes() * 0.55)
        img_floor = sum(max(3 * 1024, int(im.bytes * 0.02)) for im in self.images)
        # structural minimum: even an empty page costs ~1 KB
        return max(2 * 1024, non_img + img_floor, self.pages * 700)

    def target_feasible(self, target_kb: int) -> tuple[bool, int]:
        """(feasible?, floor_kb). GUI/engine use this for the friendly
        'closest achievable is ~X KB' message."""
        floor = self.floor_estimate_bytes()
        return target_kb * 1024 >= floor, max(1, floor // 1024)

    def summary(self) -> str:
        if not self.ok:
            return f"analysis failed: {self.error}"
        parts = [f"{label}: {self.breakdown.get(k, 0)/1024:.0f}KB ({self.pct(k):.0f}%)"
                 for k, label in CATEGORIES if self.breakdown.get(k, 0) > 0]
        return (f"{Path(self.path).name}: {self.file_bytes/1024:.0f}KB, "
                f"{self.pages} page(s) | " + ", ".join(parts))


def _stream_len(obj) -> int:
    """Raw (still-compressed) stream length in bytes, 0 if not a stream."""
    try:
        return int(obj.get("/Length", 0))
    except Exception:
        return 0


def analyze(path: str | Path, password: str = "") -> Analysis:
    """Open the PDF read-only and bucket every stream into a category.
    Never modifies the file. One pass over the object table - fast even
    on large files because streams are never decompressed."""
    import pikepdf
    from pikepdf import Name

    p = Path(path)
    res = Analysis(path=str(p))

    v = validate_pdf(p)
    if not v.ok:
        res.error = v.reason
        return res
    res.file_bytes = p.stat().st_size

    try:
        pdf = pikepdf.open(p, password=password)
    except pikepdf.PasswordError:
        res.error = "PDF is password-protected"
        res.encrypted = True
        return res
    except Exception as e:
        res.error = f"cannot parse PDF: {e}"
        return res

    try:
        res.encrypted = pdf.is_encrypted
        res.pages = len(pdf.pages)
        buckets = {k: 0 for k, _ in CATEGORIES}

        for obj in pdf.objects:
            try:
                if not isinstance(obj, pikepdf.Stream):
                    continue
                n = _stream_len(obj)
                if n <= 0:
                    continue
                subtype = obj.get("/Subtype", None)
                otype = obj.get("/Type", None)

                if subtype == Name("/Image"):
                    buckets["images"] += n
                    smask = obj.get("/SMask", None)
                    res.images.append(ImageInfo(
                        objgen=obj.objgen,
                        width=int(obj.get("/Width", 0)),
                        height=int(obj.get("/Height", 0)),
                        bytes=n,
                        filter=str(obj.get("/Filter", "")),
                        has_smask=smask is not None,
                    ))
                elif otype == Name("/Metadata"):
                    buckets["metadata"] += n
                    res.has_xmp = True
                elif otype == Name("/EmbeddedFile") or subtype == Name("/EmbeddedFile"):
                    buckets["attachments"] += n
                    res.has_attachments = True
                elif any(str(k).startswith("/FontFile") for k in obj.keys()):
                    buckets["fonts"] += n
                else:
                    # FontFile streams live INSIDE FontDescriptor dicts, so the
                    # stream itself carries /Length1 etc. Catch those:
                    if "/Length1" in obj or subtype == Name("/CIDFontType0C") \
                            or subtype == Name("/OpenType") or subtype == Name("/Type1C"):
                        buckets["fonts"] += n
                    elif subtype == Name("/Form") or subtype == Name("/XML"):
                        buckets["content"] += n
                    else:
                        buckets["content"] += n
            except Exception:
                continue  # one weird object never kills the analysis

        # Page-level flags (thumbnails) + content streams counted above
        for page in pdf.pages:
            if "/Thumb" in page:
                res.has_thumbnails = True
                t = page.obj.get("/Thumb")
                n = _stream_len(t)
                # thumbnails were bucketed as images by the loop above; move them
                if n:
                    buckets["images"] = max(0, buckets["images"] - n)
                    buckets["metadata"] += n

        # Docinfo + JavaScript flags
        try:
            if pdf.docinfo and len(pdf.docinfo.keys()) > 0:
                res.has_docinfo = True
        except Exception:
            pass
        try:
            root = pdf.Root
            names = root.get("/Names", None)
            if names is not None and "/JavaScript" in names:
                res.has_javascript = True
            if "/OpenAction" in root:
                oa = root.get("/OpenAction")
                if isinstance(oa, pikepdf.Dictionary) and oa.get("/S", None) == Name("/JavaScript"):
                    res.has_javascript = True
        except Exception:
            pass

        counted = sum(buckets[k] for k, _ in CATEGORIES if k != "other")
        buckets["other"] = max(0, res.file_bytes - counted)
        res.breakdown = buckets
        res.ok = True
    finally:
        pdf.close()
    return res


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print(analyze(f).summary())
