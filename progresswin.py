"""
SnapPDF - the floating, non-disturbing progress pill.

Why it exists: a 40-page scanned PDF being squeezed to 250 KB genuinely
takes 10-60 seconds. A silent right-click action that long feels broken.
This shows a small frameless always-on-top card (draggable, no taskbar
entry, never steals focus) with a progress bar and a live phase message,
then vanishes.

Design rules:
  * stdlib tkinter + ttk only - NOT customtkinter. The right-click path
    must stay instant, and customtkinter costs ~700 ms of import time.
  * 100% optional and defensive: if Tk can't start (headless, broken
    install), run_with_progress() silently degrades to running the job
    with no window. The job itself never depends on the window.

Usage:
    from .progresswin import run_with_progress
    result = run_with_progress("Shrinking report.pdf", job)
    # job is a callable taking one argument: status(msg) to update the label
"""

from __future__ import annotations

import queue
import threading


# palette matched to the SnapShrink/SnapPDF family theme
_BG = "#F4F7FC"
_CARD = "#FFFFFF"
_INK = "#182233"
_SOFT = "#5B6B82"
_ACCENT = "#2F7CF6"


def run_with_progress(title: str, job, enabled: bool = True):
    """Run job(status_callback) on a worker thread while a tiny floating
    window shows progress. Returns whatever job returns. If the window
    can't be created (or enabled=False), job just runs directly."""
    if not enabled:
        return job(lambda msg: None)

    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return job(lambda msg: None)

    msgs: queue.Queue = queue.Queue()
    box: dict = {"result": None, "error": None}

    def worker():
        try:
            box["result"] = job(lambda m: msgs.put(("msg", m)))
        except BaseException as e:      # surface errors to the caller
            box["error"] = e
        finally:
            msgs.put(("done", None))

    try:
        root = tk.Tk()
    except Exception:
        return job(lambda msg: None)

    try:
        root.withdraw()
        win = tk.Toplevel(root)
        win.overrideredirect(True)          # frameless
        win.attributes("-topmost", True)    # floats above Explorer
        try:
            win.attributes("-alpha", 0.97)
        except Exception:
            pass
        win.configure(bg=_BG)

        card = tk.Frame(win, bg=_CARD, highlightbackground="#E4E9F2",
                        highlightthickness=1)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(card, bg=_CARD)
        head.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(head, text="\u26a1 SnapPDF", bg=_CARD, fg=_ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(head, text=title, bg=_CARD, fg=_INK,
                 font=("Segoe UI", 10)).pack(side="left", padx=(8, 0))

        style = ttk.Style(win)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Snap.Horizontal.TProgressbar",
                        troughcolor="#E4E9F2", background=_ACCENT,
                        bordercolor="#E4E9F2", lightcolor=_ACCENT,
                        darkcolor=_ACCENT, thickness=6)
        bar = ttk.Progressbar(card, mode="indeterminate", length=320,
                              style="Snap.Horizontal.TProgressbar")
        bar.pack(padx=14, pady=(6, 4), fill="x")
        bar.start(14)

        status = tk.Label(card, text="starting...", bg=_CARD, fg=_SOFT,
                          anchor="w", font=("Segoe UI", 9))
        status.pack(fill="x", padx=14, pady=(0, 10))

        # bottom-right corner placement, above the taskbar
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = max(360, win.winfo_reqwidth()), win.winfo_reqheight()
        win.geometry(f"{w}x{h}+{sw - w - 24}+{sh - h - 80}")

        # draggable anywhere on the card
        drag = {"x": 0, "y": 0}

        def press(e):
            drag["x"], drag["y"] = e.x_root - win.winfo_x(), e.y_root - win.winfo_y()

        def move(e):
            win.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")

        for widget in (card, head, status):
            widget.bind("<ButtonPress-1>", press)
            widget.bind("<B1-Motion>", move)

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            closed = False
            try:
                while True:
                    kind, payload = msgs.get_nowait()
                    if kind == "msg":
                        status.configure(text=str(payload)[:90])
                    elif kind == "done":
                        closed = True
            except queue.Empty:
                pass
            if closed:
                root.after(150, root.destroy)   # brief beat so 'done' is visible
            else:
                root.after(80, poll)

        root.after(80, poll)
        root.mainloop()
    except Exception:
        # window died mid-run: make sure the job still completes
        if box["result"] is None and box["error"] is None:
            return job(lambda msg: None)
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    if box["error"] is not None:
        raise box["error"]
    return box["result"]
