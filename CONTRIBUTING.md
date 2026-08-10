# Contributing to SnapPDF

Thanks for considering a contribution — SnapPDF is a small, focused tool
and even small pull requests are genuinely useful.

## Ways to contribute

- **Report a bug** — [open an issue](../../issues) with your Windows
  version, the PDF that triggered it if possible (or a description of
  what's in it — scanned images, forms, embedded fonts, etc.), and the
  exact steps to reproduce.
- **Suggest a feature** — check existing issues first in case it's
  already tracked, then open a new one describing the use case (not just
  the feature) so it's clear what problem it solves.
- **Submit a pull request** — for anything beyond a typo fix, please open
  an issue first to discuss the approach before writing code. This avoids
  spending time on a PR that doesn't fit the project's direction.

## Development setup

```bash
git clone https://github.com/vijayparmar/snappdf.git
cd snappdf
pip install -r requirements.txt
```

The core engine (`sppack/analysis.py`, `sppack/engine.py`,
`sppack/textmode.py`) is pure Python and runs on any OS. The GUI
(`sppack/gui.py`), background daemon (`sppack/daemon.py`), and right-click
context menu (`sppack/contextmenu.py`) are Windows-only, since they depend
on `pywin32`, `pystray`, and `pynput`.

## Running the test suite

```bash
python -m sppack --selftest
```

This runs 58 checks covering validation, the storage-weightage analysis,
every optimization phase, merge, PDF-to-image and image-to-PDF conversion,
both "Keep only..." reduction modes, and error handling. **Please run this
before opening a PR** — a green self-test doesn't guarantee a change is
correct, but a red one guarantees it needs another look.

If you're changing the engine (`engine.py`, `analysis.py`, or
`textmode.py`), please also add a new self-test check covering your change
rather than only testing manually — the self-test suite is what keeps this
project safe to modify.

## Code style

- Match the existing style in the file you're editing rather than
  introducing a new one — this project deliberately avoids heavy
  formatting tooling in favor of consistency by example.
- Prefer explicit, readable code over clever one-liners; this is a tool
  people trust with their documents, and clarity matters more than
  brevity.
- Keep functions focused — the engine's phase-based design
  (Structure / Metadata / Images) exists so each phase can be reasoned
  about, tested, and toggled independently. New functionality should
  generally fit that pattern rather than crossing phase boundaries.

## Building the Windows installer

```bash
pip install pyinstaller
python installer/build_app.py
# then open installer/SnapPDF.iss in Inno Setup and press F9
```

See the `installer/` folder for how packaging works, including the size
audit that runs automatically after each build.

## Questions

Open a [discussion or issue](../../issues) — happy to help you get
oriented in the codebase.
