<div align="center">
  <img src="assets/cover.gif" width="100%" alt="SnapPDF — Right-click PDF optimization for Windows"/>
</div>

<br>

<div align="center">

  <a href="https://github.com/vijayparmar/snappdf/releases/latest"><img src="https://img.shields.io/github/v/release/vijayparmar/snappdf?color=2F7CF6&label=Download&logo=windows&logoColor=white" alt="Latest Release"></a>
  <a href="https://github.com/vijayparmar/snappdf/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?logo=opensourceinitiative&logoColor=white" alt="MIT License"></a>
  <a href="https://pypi.org/project/snappdf/"><img src="https://img.shields.io/pypi/v/snappdf?logo=pypi&logoColor=white&color=orange" alt="PyPI Version"></a>
  <a href="https://pypi.org/project/snappdf/"><img src="https://img.shields.io/pypi/dm/snappdf?logo=pypi&logoColor=white&label=pip%20installs" alt="PyPI Downloads"></a>
  <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?logo=windows&logoColor=white" alt="Windows 10/11">
  <img src="https://img.shields.io/badge/Admin%20Rights-Not%20Required-brightgreen" alt="No Admin Required">
  <img src="https://img.shields.io/badge/Price-Free%20Forever-2F7CF6" alt="Free Forever">

</div>

<br>

<div align="center">
  <h1>⚡ SnapPDF</h1>
  <p><strong>Right-click. Pick a size. Done.</strong></p>
  <p>Shrink, merge and convert PDFs on Windows — without ever opening an app.</p>
</div>

<div align="center">
  <a href="https://www.linkedin.com/in/thevijayparmar/">
    <img src="https://img.shields.io/badge/LinkedIn-Vijay%20Parmar-0077B5?logo=linkedin&logoColor=white" alt="LinkedIn">
  </a>
  &nbsp;
  <a href="https://github.com/vijayparmar/snappdf/issues">
    <img src="https://img.shields.io/badge/Report%20Bug-Issues-red?logo=github" alt="Report Bug">
  </a>
  &nbsp;
  <a href="https://github.com/vijayparmar/snappdf/issues">
    <img src="https://img.shields.io/badge/Request%20Feature-Ideas-blueviolet?logo=github" alt="Request Feature">
  </a>
</div>

---

## 🎬 Full App Demo

<div align="center">
  <img src="assets/full-launch_Edited.gif" width="80%" alt="SnapPDF — Full product walkthrough"/>
</div>

---

## ⌨️ Instant Hotkey — Ctrl+Alt+P

Select one or more PDFs in Explorer. Press `Ctrl+Alt+P`. Optimized in place, no window ever opens.

<div align="center">
  <img src="assets/screenshot-rightclick-menu.png" width="70%" alt="Right-click context menu — SnapPDF options"/>
</div>

<br>

*The full right-click menu: Quick Optimize, Shrink to size, Shrink to % of size, Convert to images, Merge PDFs, Merge && shrink to, Keep only Text and Vectors, Keep only Text, and Combine to PDF for selected images.*

---

## 📐 Shrink to an Exact Size

Tell SnapPDF the max file size you want — 10 KB up to 5 MB. It finds the right structure, metadata, and image-quality combination automatically, no trial and error.

<div align="center">
  <img src="assets/screenshot-tray.png" width="70%" alt="SnapPDF quietly running in the system tray"/>
</div>

<br>

*SnapPDF starts with Windows and waits quietly in the tray — the hotkey is always live, without an app window open.*

---

## 🛠️ Full Control from the Tool

Need more than a right-click preset? Open SnapPDF itself for a live storage-weightage breakdown (Images / Fonts / Content / Attachments / Metadata / Structure), per-phase toggles, a quality slider, and an apx. output-size estimate before you commit.

<div align="center">
  <img src="assets/screenshot-tool-window.png" width="80%" alt="SnapPDF tool window — SINGLE mode analysis panel"/>
</div>

---

## 🎯 Multiple Use Cases

<div align="center">
  <img src="assets/usecase-grid.gif" width="100%" alt="Multiple SnapPDF use cases"/>
</div>

---

## Why SnapPDF exists

Every workflow eventually produces a PDF that's too big. A scanned form is 8 MB when the portal caps uploads at 2 MB. A report with embedded photos won't attach to an email. A dozen invoices need to become one file before they can be filed.

The usual fixes are all broken in their own way:
- Online PDF compressors **upload your documents** to someone else's server
- Desktop editors **overwrite your original** file with no way back
- None of them let you say *"just keep it under 250 KB"* and have it actually work — or tell you honestly when a target isn't realistic

SnapPDF solves all three, right from the Windows right-click menu.

---

## What it does

| Feature | Detail |
|---|---|
| **Shrink** | Structure rewrite, metadata/attachment stripping, image re-encoding — 8 built-in presets |
| **Target a size** | 9 size presets (10 KB → 5 MB) or a percentage of the original (50–95%) |
| **Merge** | Combine multiple PDFs into one, with an optional size target on the result |
| **Convert to images** | Every page exported as JPG at 72–300 DPI |
| **Combine to PDF** | Turn selected image files into a single PDF |
| **Keep only Text and Vectors** | Strips every image; text, vector art, fonts, and annotations stay untouched |
| **Keep only Text** | Maximum reduction — rebuilds every page from its text alone in a standard font |
| **Hotkey** | `Ctrl+Alt+P` — optimizes whatever PDFs are selected in Explorer, instantly |
| **Originals safe** | Every action creates a new file; the source is never modified |
| **Offline** | No internet, no uploads, no accounts, no telemetry |

---

## The "Keep only..." modes

Two extra, more aggressive reductions for when you want the smallest possible file:

- **Keep only Text and Vectors** — deletes every raster image; text, vector drawings, fonts, and annotations are left exactly as they were.
- **Keep only Text** — the most aggressive mode. Every page is rebuilt from nothing but its text: each character's Unicode value, position, and size is extracted, then redrawn using one of the 14 standard PDF fonts that every reader can render without embedded font data. Images, vector art, annotations, forms, and metadata are all gone.

  This mode works best for Latin-script text (English and most European languages). Non-Latin scripts are replaced with `?` — SnapPDF warns you when this happens rather than doing it silently.

---

## 🖥️ Install (Windows App)

1. Download the latest `SnapPDFSetup.exe` from [**Releases →**](../../releases)
2. Run it — no admin rights needed, installs to your user folder
3. Right-click any PDF → **SnapPDF** → pick an option

> **SmartScreen warning?** Click **More info → Run anyway**. This is expected for independently-published tools. See [SECURITY.md](SECURITY.md) for why this happens and how to verify the app yourself.

---

## 🐍 Python Library (pip install)

SnapPDF's optimization engine is also available as a pip-installable Python library — useful for scripts, automation, and batch workflows. It's pure Python and runs on any OS (the GUI, hotkey, and right-click menu are Windows-only).

```bash
pip install snappdf
```

### Quick start

```python
from sppack.engine import process_pdf, merge_pdfs, pdf_to_images, images_to_pdf, Options

# Shrink a PDF to under 250 KB
process_pdf("report.pdf", Options(target_kb=250))

# Shrink to 50% of its original size
process_pdf("report.pdf", Options(target_pct=50))

# Merge several PDFs, then shrink the result
merge_pdfs(["a.pdf", "b.pdf", "c.pdf"], Options(target_kb=500))

# Convert every page to a JPG at 150 DPI
pdf_to_images("scan.pdf", dpi=150)

# Combine images into a single PDF
images_to_pdf(["page1.jpg", "page2.jpg"])

# Maximum reduction: keep only the text
process_pdf("report.pdf", Options(reduction_mode="text_only"))
```

### Options reference

```python
Options(
    do_structure=True,     # qpdf rewrite: garbage collection, stream recompression, image dedup
    do_metadata=True,      # strip XMP/DocInfo, thumbnails, attachments, JavaScript
    do_images=True,        # re-encode embedded images
    img_quality=75,        # starting JPEG quality (30-90)
    max_dpi=None,          # optional cap on effective image DPI
    grayscale=False,       # convert images to grayscale
    linearize=False,       # Fast Web View
    target_kb=None,        # absolute size target in KB
    target_pct=None,       # percent of source size (50-95)
    reduction_mode=None,   # None | "text_vectors" | "text_only"
)
```

> **Requires:** Python 3.10+, Windows (for GUI/daemon/context-menu features). The core engine (`process_pdf`, `merge_pdfs`, `pdf_to_images`, `images_to_pdf`) runs on any OS.

---

## 🔧 Building from Source

```bash
# Clone the repo
git clone https://github.com/vijayparmar/snappdf.git
cd snappdf

# Install dependencies
pip install -r requirements.txt

# Run self-tests (58 checks, no Windows needed)
python -m sppack --selftest

# Build the Windows app
python installer/build_app.py
# Then open installer/SnapPDF.iss in Inno Setup and press F9
```

See [`installer/`](installer) for the full build pipeline details.

---

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get started. Check [Issues](../../issues) for open ideas and bugs.

---

## 📜 License

MIT — see [LICENSE](LICENSE). Free for personal and commercial use.

---

<div align="center">
  <strong>Open Source · Free Forever</strong>
  <br/>
  Developed by <a href="https://www.linkedin.com/in/thevijayparmar/">Vijay Parmar</a>
  <br/><br/>
  <a href="https://www.linkedin.com/in/thevijayparmar/">
    <img src="https://img.shields.io/badge/LinkedIn-Connect-0077B5?logo=linkedin&logoColor=white" alt="LinkedIn"/>
  </a>
  &nbsp;
  <a href="https://github.com/vijayparmar/snappdf/issues">
    <img src="https://img.shields.io/badge/GitHub-Issues-181717?logo=github" alt="GitHub Issues"/>
  </a>
</div>
