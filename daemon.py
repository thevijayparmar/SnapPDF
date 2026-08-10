"""
SnapPDF - background helper + right-click handlers.

1. Tray icon with a low-level keyboard hook: Ctrl+Alt+P optimizes the
   PDFs currently selected in Explorer using the saved hotkey preset
   (Structure + Metadata + Images@q75 by default). Zero polling.
2. All the --ctx-* right-click actions land here, wrapped in the floating
   progress pill (progresswin) + toast notifications.
3. The merge singleton guard (see contextmenu.py docstring): classic
   registry verbs fire once per selected file, but merge needs the whole
   selection in ONE process.

Windows-only where it touches Explorer/COM; everything degrades cleanly.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import config as cfgmod
from .engine import (IMAGE_EXT, PDF_EXT, Options, images_to_pdf, merge_pdfs,
                     pdf_to_images, process_batch, process_pdf)

IS_WINDOWS = sys.platform == "win32"


# --------------------------------------------------------------------------
# Explorer selection (SnapShrink's pywin32 trick, filtered for PDFs/images)
# --------------------------------------------------------------------------

def get_explorer_selection(exts: set[str] | None = None) -> list[str]:
    """Files currently selected in the foreground Explorer window / Desktop.
    Defensive: any failure returns []."""
    if not IS_WINDOWS:
        return []
    try:
        import pythoncom
        import win32com.client
        import win32gui
    except ImportError:
        print("[HOOK] pywin32 not installed - cannot read Explorer selection")
        return []

    pythoncom.CoInitialize()
    try:
        fg = win32gui.GetForegroundWindow()
        cls = win32gui.GetClassName(fg)
        shell = win32com.client.Dispatch("Shell.Application")
        paths: list[str] = []
        for win in shell.Windows():
            try:
                if int(win.HWND) == int(fg):
                    for item in win.Document.SelectedItems():
                        paths.append(str(item.Path))
                    break
            except Exception:
                continue
        if not paths and cls in ("Progman", "WorkerW"):
            try:
                for win in shell.Windows():
                    if win.Name in ("Desktop", "Windows Explorer"):
                        for item in win.Document.SelectedItems():
                            paths.append(str(item.Path))
                        break
            except Exception:
                pass
        if exts:
            paths = [p for p in paths
                     if Path(p).suffix.lower() in exts and Path(p).is_file()]
        return paths
    except Exception as e:
        print(f"[HOOK] could not read Explorer selection: {e}")
        return []
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Feedback (toast + beep, no window)
# --------------------------------------------------------------------------

def notify(title: str, message: str, cfg: dict, error: bool = False) -> None:
    if cfg.get("sound_feedback", True):
        try:
            import winsound
            winsound.MessageBeep(0x00000010 if error else 0x00000000)
        except Exception:
            pass
    if cfg.get("toast_feedback", True):
        try:
            from winotify import Notification
            Notification(app_id="SnapPDF", title=title, msg=message).show()
        except Exception as e:
            print(f"[TOAST] unavailable ({e}) - {title} | {message}")


# --------------------------------------------------------------------------
# Merge singleton guard
# --------------------------------------------------------------------------

_GUARD_TTL = 4.0   # seconds - Explorer launches the N processes within ~1s


def _merge_guard(tag: str) -> bool:
    """True = this process should do the work. False = a sibling process
    (from the same multi-select right-click) already owns it - exit quietly."""
    lock = Path(tempfile.gettempdir()) / f"snappdf-{tag}.lock"
    now = time.time()
    try:
        if lock.exists() and now - lock.stat().st_mtime < _GUARD_TTL:
            return False
        lock.write_text(str(os.getpid()))
        # tiny race window: whoever wrote last wins; re-check after a beat
        time.sleep(0.15)
        return lock.read_text() == str(os.getpid())
    except Exception:
        return True   # guard failure must never block the user's action


# --------------------------------------------------------------------------
# The quick / ctx jobs
# --------------------------------------------------------------------------

_busy = threading.Lock()


def _progress_run(title: str, cfg: dict, job):
    """Run job under the floating progress pill (if enabled)."""
    from .progresswin import run_with_progress
    return run_with_progress(title, job, enabled=cfg.get("progress_window", True))


def _report(results: list, cfg: dict, verb: str = "optimized"):
    ok = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]
    unmet = [r for r in ok if r.target_kb and not r.target_met]
    non_latin = [r for r in ok if getattr(r, "non_latin_detected", False)]
    if ok and not bad:
        if len(ok) == 1:
            r = ok[0]
            out_name = Path(r.output).name
            if r.target_kb and not r.target_met:
                msg = (f"{out_name} - target {r.target_kb}KB wasn't reachable; "
                       f"closest is {r.out_bytes//1024}KB"
                       + (f" (floor ~{r.floor_kb}KB)" if r.floor_kb else ""))
                notify("SnapPDF - best effort", msg, cfg, error=True)
            elif getattr(r, "non_latin_detected", False):
                notify("SnapPDF - check output", f"{out_name}: some non-Latin "
                       "text couldn't be kept (base-14 fonts are Latin-only) "
                       "and was replaced with '?'.", cfg, error=True)
            else:
                saved = (1 - r.out_bytes / r.in_bytes) * 100 if r.in_bytes else 0
                notify("SnapPDF", f"{out_name}  ({r.out_bytes/1024:.0f} KB, "
                                  f"{saved:.0f}% smaller)", cfg)
        else:
            saved = sum(r.in_bytes for r in ok) - sum(r.out_bytes for r in ok)
            extra = f", {len(unmet)} hit their floor" if unmet else ""
            extra += f", {len(non_latin)} had non-Latin text replaced" if non_latin else ""
            notify("SnapPDF", f"{len(ok)} PDFs {verb}, "
                              f"{saved/1024:.0f} KB saved{extra}", cfg)
    elif ok and bad:
        notify("SnapPDF", f"{len(ok)} {verb}, {len(bad)} failed: "
                          f"{bad[0].error}", cfg, error=True)
    elif bad:
        notify("SnapPDF", bad[0].error or "unknown error", cfg, error=True)


def run_quick(paths: list[str] | None = None,
              ctx_size_kb: int | None = None,
              ctx_pct: int | None = None) -> None:
    """Hotkey (Ctrl+Alt+P) or right-click Quick/Size/% presets.
    paths=None -> read Explorer selection (hotkey path)."""
    if not _busy.acquire(blocking=False):
        print("[HOOK] already busy - ignoring")
        return
    try:
        cfg = cfgmod.load()
        files = paths if paths is not None else get_explorer_selection(PDF_EXT)
        files = [f for f in files if Path(f).suffix.lower() in PDF_EXT]
        if not files:
            notify("SnapPDF", "No PDF files selected.", cfg, error=True)
            return

        if ctx_size_kb is not None:
            opts = cfgmod.to_options(cfg, hotkey_preset=True)
            opts.target_kb = ctx_size_kb
            opts.target_pct = None
            title = f"Shrinking to {ctx_size_kb}KB"
        elif ctx_pct is not None:
            opts = cfgmod.to_options(cfg, hotkey_preset=True)
            opts.target_kb = None
            opts.target_pct = ctx_pct
            title = f"Shrinking to {ctx_pct}%"
        else:
            opts = cfgmod.to_options(cfg, hotkey_preset=True)
            title = "Quick Optimize"
        name = Path(files[0]).name if len(files) == 1 else f"{len(files)} PDFs"

        def job(status):
            def per_file(done, total, r):
                status(f"[{done}/{total}] {Path(r.source).name}: done")
                print(f"[ENGINE] {r.summary()}")
            status(f"{title}: {name}")
            return process_batch(files, opts,
                                 progress=per_file)

        results = _progress_run(f"{title} - {name}", cfg, job)
        _report(results, cfg)
    finally:
        _busy.release()


def run_to_images(dpi: int, paths: list[str] | None = None) -> None:
    cfg = cfgmod.load()
    files = paths if paths is not None else get_explorer_selection(PDF_EXT)
    files = [f for f in files if Path(f).suffix.lower() in PDF_EXT]
    if not files:
        notify("SnapPDF", "No PDF files selected.", cfg, error=True)
        return

    def job(status):
        out = []
        for f in files:
            out.append(pdf_to_images(f, dpi=dpi,
                                     progress=lambda m: status(f"{Path(f).name}: {m}")))
        return out

    results = _progress_run(f"Converting to images @ {dpi} DPI", cfg, job)
    ok = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]
    if ok and not bad:
        pages = sum(r.pages for r in ok)
        where = Path(ok[0].output).name if len(ok) == 1 else f"{len(ok)} folders"
        notify("SnapPDF", f"{pages} page(s) exported -> {where}", cfg)
    else:
        _report(results, cfg, verb="converted")


def run_merge(target_kb: int | None = None) -> None:
    """Multi-select merge (and optional shrink). Singleton-guarded: only
    the first of the N per-file processes does the work."""
    if not _merge_guard("merge"):
        return
    cfg = cfgmod.load()
    files = get_explorer_selection(PDF_EXT)
    if len(files) < 2:
        notify("SnapPDF", "Select 2 or more PDFs to merge (in Explorer), "
                          "then right-click.", cfg, error=True)
        return
    opts = cfgmod.to_options(cfg, hotkey_preset=True)
    opts.target_kb = target_kb
    opts.target_pct = None
    if target_kb is None:
        opts.do_images = False       # plain merge = lossless, fast
    title = f"Merging {len(files)} PDFs" + (f" -> {target_kb}KB" if target_kb else "")

    def job(status):
        return merge_pdfs(files, opts, progress=status)

    r = _progress_run(title, cfg, job)
    _report([r], cfg, verb="merged")


def run_reduction(mode: str, paths: list[str] | None = None) -> None:
    """Right-click 'Keep only Text and Vectors' / 'Keep only Text'."""
    cfg = cfgmod.load()
    files = paths if paths is not None else get_explorer_selection(PDF_EXT)
    files = [f for f in files if Path(f).suffix.lower() in PDF_EXT]
    if not files:
        notify("SnapPDF", "No PDF files selected.", cfg, error=True)
        return
    opts = Options(reduction_mode=mode)
    label = "Keep only Text and Vectors" if mode == "text_vectors" else "Keep only Text"
    name = Path(files[0]).name if len(files) == 1 else f"{len(files)} PDFs"

    def job(status):
        def per_file(done, total, r):
            status(f"[{done}/{total}] {Path(r.source).name}: done")
        status(f"{label}: {name}")
        return process_batch(files, opts, progress=per_file)

    results = _progress_run(f"{label} - {name}", cfg, job)
    _report(results, cfg, verb=label.lower())


def run_imgs2pdf() -> None:
    """Multi-select images -> one PDF. Same singleton guard."""
    if not _merge_guard("imgs2pdf"):
        return
    cfg = cfgmod.load()
    files = get_explorer_selection(IMAGE_EXT)
    if not files:
        notify("SnapPDF", "No image files selected.", cfg, error=True)
        return

    def job(status):
        return images_to_pdf(files, progress=status)

    r = _progress_run(f"Combining {len(files)} image(s) to PDF", cfg, job)
    _report([r], cfg, verb="combined")


# --------------------------------------------------------------------------
# Tray icon + hotkey listener
# --------------------------------------------------------------------------

def _tray_image():
    """Simple in-memory tray icon: bolt on a page."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 4, 56, 60], radius=8, fill=(47, 124, 246, 255))
    d.rectangle([16, 14, 48, 18], fill=(255, 255, 255, 230))
    d.rectangle([16, 24, 48, 28], fill=(255, 255, 255, 230))
    d.polygon([(36, 30), (24, 46), (32, 46), (28, 58), (44, 40), (35, 40)],
              fill=(255, 214, 64, 255))
    return img


def start() -> int:
    if not IS_WINDOWS:
        print("The background hotkey daemon is Windows-only.")
        print("The window (python -m sppack) works everywhere.")
        return 1
    try:
        import pystray
        from pynput import keyboard
    except ImportError:
        print("Missing packages. Run:  pip install pystray pynput winotify pywin32")
        return 1

    cfg = cfgmod.load()
    hotkey = cfg.get("hotkey", "<ctrl>+<alt>+p")

    print("=" * 58)
    print(" SnapPDF daemon running. Tray icon is in the taskbar corner.")
    print(f" Hotkey: {hotkey} -> optimizes PDFs selected in Explorer")
    print(f" Preset: Structure+Metadata+Images q{cfg['hk_img_quality']}")
    print(f" Config: {cfgmod.config_path()}")
    print("=" * 58)

    def on_hotkey():
        print(f"\n[HOOK] {hotkey} pressed")
        threading.Thread(target=run_quick, daemon=True).start()

    listener = keyboard.GlobalHotKeys({hotkey: on_hotkey})
    listener.start()

    def do_open_gui(icon=None, item=None):
        import subprocess
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable])
        else:
            subprocess.Popen([sys.executable, "-m", "sppack"])

    def do_quit(icon, item):
        listener.stop()
        icon.stop()

    icon = pystray.Icon(
        "snappdf", _tray_image(), "SnapPDF",
        menu=pystray.Menu(
            pystray.MenuItem("Open SnapPDF", do_open_gui, default=True),
            pystray.MenuItem(f"Hotkey: {hotkey}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", do_quit),
        ),
    )
    try:
        icon.run()
    except KeyboardInterrupt:
        listener.stop()
    return 0
