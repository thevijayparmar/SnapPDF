"""
SnapPDF - the window.

Two modes via a SINGLE / BULK toggle at the top (Vijay's spec):

  BULK   - drop one or more PDFs, pick a preset from a dropdown, Optimize.
           Every file gets the same treatment, processed one by one.

  SINGLE - drop exactly one PDF. It's analyzed immediately and the panel
           shows the storage-weightage breakdown (Images / Fonts / Content
           / Attachments / Metadata / Structure) with per-PHASE checkboxes
           (Structure, Metadata, Images - phase-level per Vijay, not
           per-pass), Select all / Clear all, an image-quality slider with
           a live "apx. output size / apx. time" estimate, a presets
           dropdown, and an optional exact size target.

Visual language = the SnapShrink v1.26 white/glassmorphic family theme:
same COLOR dict, same F() font helper, same About popup with credits.
Heavy imports live INSIDE this module - it's only imported when a window
is actually wanted.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

import customtkinter as ctk

from . import config as cfgmod
from .analysis import CATEGORIES, Analysis, analyze
from .engine import (DPI_CHOICES, IMAGE_EXT, MAX_QUALITY, MIN_QUALITY,
                     PDF_EXT, Options, Result, estimate, images_to_pdf,
                     merge_pdfs, pdf_to_images, process_batch, process_pdf)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_OK = True
except Exception:
    DND_OK = False

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ------------- family palette (identical to SnapShrink v1.26) --------------
COLOR = {
    "bg":          "#F4F7FC",
    "card":        "#FFFFFF",
    "card_border": "#E4E9F2",
    "ink":         "#182233",
    "ink_soft":    "#5B6B82",
    "bolt":        "#2F7CF6",
    "bolt_hover":  "#1E5FD0",
    "bolt_soft":   "#EAF1FF",
    "green":       "#1FA75C",
    "red":         "#E0475B",
    "track":       "#E4E9F2",
}
# category bar colors for the weightage panel
CAT_COLOR = {
    "images": "#2F7CF6", "fonts": "#8B5CF6", "content": "#1FA75C",
    "attachments": "#F59E0B", "metadata": "#EC4899", "other": "#94A3B8",
}

FONT_FAMILY = "Segoe UI"


def F(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


class _Root(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.configure(fg_color=COLOR["bg"])
        if DND_OK:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self._dnd_ready = True
            except Exception as e:
                print(f"[GUI] drag-drop unavailable: {e}")
                self._dnd_ready = False
        else:
            self._dnd_ready = False


def _parse_dropped(data: str) -> list[str]:
    out, buf, in_brace = [], "", False
    for ch in data:
        if ch == "{":
            in_brace, buf = True, ""
        elif ch == "}":
            in_brace = False
            out.append(buf); buf = ""
        elif ch == " " and not in_brace:
            if buf:
                out.append(buf); buf = ""
        else:
            buf += ch
    if buf:
        out.append(buf)
    return [p for p in out if p]


def _fmt_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n/1024/1024:.1f} MB"
    return f"{n/1024:.0f} KB"


class SnapPDFApp:
    def __init__(self, files: list[str] | None = None):
        self.cfg = cfgmod.load()
        self.files: list[str] = []
        self.analysis: Analysis | None = None
        self.events: queue.Queue = queue.Queue()
        self.running = False

        self.root = _Root()
        self.root.title("SnapPDF")
        self.root.geometry("720x860")
        self.root.minsize(660, 780)
        self._build()

        if files:
            self.add_files(files)
        self.root.after(80, self._drain_events)

    # ------------------------------------------------------------ theme helpers
    def _label(self, parent, text):
        return ctk.CTkLabel(parent, text=text, font=F(13),
                            text_color=COLOR["ink_soft"])

    def _btn(self, parent, text, command, width=None, height=32,
             font=None, style="primary"):
        """style: primary (solid blue) | outline (blue border) | ghost (soft grey)"""
        kw = dict(text=text, command=command, corner_radius=10,
                  font=font or F(13, "bold"))
        if width:
            kw["width"] = width
        if height:
            kw["height"] = height
        if style == "primary":
            kw.update(fg_color=COLOR["bolt"], hover_color=COLOR["bolt_hover"],
                      text_color="#FFFFFF")
        elif style == "outline":
            kw.update(fg_color="transparent", hover_color=COLOR["bolt_soft"],
                      text_color=COLOR["bolt"], border_width=1,
                      border_color=COLOR["bolt"])
        else:  # ghost
            kw.update(fg_color=COLOR["bolt_soft"], hover_color=COLOR["card_border"],
                      text_color=COLOR["ink_soft"])
        return ctk.CTkButton(parent, **kw)

    # ---------------------------------------------------------------- build
    def _build(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(2, weight=1)

        # ---- header ----
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.grid(row=0, column=0, pady=(20, 4), sticky="n")
        ctk.CTkLabel(header, text="\u26a1", font=F(22),
                     text_color=COLOR["bolt"]).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(header, text="SnapPDF", font=F(24, "bold"),
                     text_color=COLOR["ink"]).pack(side="left")

        # ---- mode toggle ----
        self.v_mode = ctk.StringVar(value="SINGLE")
        seg = ctk.CTkSegmentedButton(
            self.root, values=["SINGLE", "BULK"], variable=self.v_mode,
            command=lambda _v: self._mode_changed(),
            font=F(13, "bold"), corner_radius=10,
            fg_color=COLOR["track"], selected_color=COLOR["bolt"],
            selected_hover_color=COLOR["bolt_hover"],
            unselected_color=COLOR["card"], unselected_hover_color=COLOR["bolt_soft"],
            text_color=COLOR["ink"])
        seg.grid(row=1, column=0, pady=(2, 8))

        # ---- drop zone / file list ----
        drop = ctk.CTkFrame(self.root, corner_radius=16, fg_color=COLOR["card"],
                            border_width=1, border_color=COLOR["card_border"])
        drop.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="nsew")
        drop.grid_columnconfigure(0, weight=1)
        drop.grid_rowconfigure(0, weight=1)

        self.filebox = ctk.CTkTextbox(
            drop, activate_scrollbars=True, corner_radius=12,
            fg_color=COLOR["bolt_soft"], text_color=COLOR["ink_soft"],
            font=F(13), border_width=0, height=90)
        self.filebox.grid(row=0, column=0, padx=14, pady=(14, 6), sticky="nsew")
        self.filebox.configure(state="disabled")

        btnrow = ctk.CTkFrame(drop, fg_color="transparent")
        btnrow.grid(row=1, column=0, pady=(0, 12))
        self._btn(btnrow, "Add PDF(s)...", self.browse, width=120,
                  style="outline").pack(side="left", padx=4)
        self._btn(btnrow, "Clear", self.clear, width=80,
                  style="ghost").pack(side="left", padx=4)

        if self.root._dnd_ready:
            self.filebox.drop_target_register(DND_FILES)
            self.filebox.dnd_bind("<<Drop>>", self._on_drop)

        # ---- SINGLE panel: analysis + phases ----
        self.panel_single = ctk.CTkFrame(self.root, corner_radius=16,
                                         fg_color=COLOR["card"], border_width=1,
                                         border_color=COLOR["card_border"])
        self._build_single_panel(self.panel_single)

        # ---- BULK panel: preset dropdown ----
        self.panel_bulk = ctk.CTkFrame(self.root, corner_radius=16,
                                       fg_color=COLOR["card"], border_width=1,
                                       border_color=COLOR["card_border"])
        self._build_bulk_panel(self.panel_bulk)

        # ---- actions ----
        a = ctk.CTkFrame(self.root, fg_color="transparent")
        a.grid(row=4, column=0, padx=20, sticky="ew")
        a.grid_columnconfigure(0, weight=1)

        self.bar = ctk.CTkProgressBar(a, progress_color=COLOR["bolt"],
                                      fg_color=COLOR["track"], corner_radius=6,
                                      height=8)
        self.bar.set(0)
        self.bar.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(2, 8))

        self.status = ctk.CTkLabel(a, text="Drop a PDF above to analyze it.",
                                   anchor="w", justify="left", font=F(13),
                                   text_color=COLOR["ink_soft"])
        self.status.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        self.btn_go = self._btn(a, "Optimize", self.optimize, height=46,
                                font=F(16, "bold"), style="primary")
        self.btn_go.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        self._btn(a, "Save defaults", self.save_defaults, width=120,
                  style="outline").grid(row=2, column=1, padx=(10, 0), pady=(0, 14))
        self._btn(a, "About", self.show_about, width=72,
                  style="ghost").grid(row=2, column=2, padx=(10, 0), pady=(0, 14))

        ctk.CTkLabel(self.root, text="Originals are never modified."
                     + ("" if self.root._dnd_ready
                        else "   (drag-drop off: pip install tkinterdnd2)"),
                     text_color=COLOR["ink_soft"], font=F(11)
                     ).grid(row=5, column=0, pady=(0, 10))

        self._mode_changed()

    # ---------------------------------------------------------- single panel
    def _build_single_panel(self, s):
        s.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(s, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 2))
        top.grid_columnconfigure(1, weight=1)
        self._label(top, "Preset").grid(row=0, column=0, sticky="w")
        self.v_preset = ctk.StringVar(value=self.cfg.get("bulk_preset",
                                                         "Balanced (recommended)"))
        ctk.CTkOptionMenu(top, values=list(cfgmod.PRESETS), variable=self.v_preset,
                          command=lambda _v: self._apply_preset(), width=230,
                          fg_color=COLOR["bolt"], button_color=COLOR["bolt_hover"],
                          button_hover_color=COLOR["bolt_hover"],
                          dropdown_fg_color=COLOR["card"],
                          dropdown_text_color=COLOR["ink"], font=F(13),
                          corner_radius=8).grid(row=0, column=1, sticky="w", padx=8)
        self._btn(top, "Select all", lambda: self._set_phases(True), width=84,
                  style="ghost").grid(row=0, column=2, padx=(4, 2))
        self._btn(top, "Clear all", lambda: self._set_phases(False), width=80,
                  style="ghost").grid(row=0, column=3, padx=2)

        # ---- the weightage panel: one row per category ----
        self.wrows: dict[str, dict] = {}
        wframe = ctk.CTkFrame(s, fg_color="transparent")
        wframe.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 4))
        wframe.grid_columnconfigure(1, weight=1)

        # which phase checkbox controls which categories
        #   structure  -> other ("Structure & overhead")
        #   metadata   -> metadata + attachments
        #   images     -> images
        #   fonts/content -> shown for information, optimization = v2
        self.v_ph = {
            "structure": ctk.BooleanVar(value=self.cfg["do_structure"]),
            "metadata": ctk.BooleanVar(value=self.cfg["do_metadata"]),
            "images": ctk.BooleanVar(value=self.cfg["do_images"]),
        }
        phase_of = {"other": "structure", "metadata": "metadata",
                    "attachments": "metadata", "images": "images"}
        self._phase_checkboxes: list = []
        self.v_reduction_mode: str | None = None

        for r, (key, label) in enumerate(CATEGORIES):
            phase = phase_of.get(key)
            if phase:
                cb = ctk.CTkCheckBox(
                    wframe, text="", width=24, variable=self.v_ph[phase],
                    command=self._refresh_estimate,
                    fg_color=COLOR["bolt"], hover_color=COLOR["bolt_hover"],
                    border_color=COLOR["track"], checkmark_color="#FFFFFF")
                cb.grid(row=r, column=0, sticky="w")
                self._phase_checkboxes.append(cb)
            else:
                ctk.CTkLabel(wframe, text="\u2013", width=24, font=F(12),
                             text_color=COLOR["ink_soft"]).grid(row=r, column=0)
            name = ctk.CTkLabel(wframe, text=label, anchor="w", font=F(12),
                                text_color=COLOR["ink"])
            name.grid(row=r, column=1, sticky="w", padx=(2, 8))
            bar = ctk.CTkProgressBar(wframe, height=10, corner_radius=5,
                                     progress_color=CAT_COLOR[key],
                                     fg_color=COLOR["track"], width=180)
            bar.set(0)
            bar.grid(row=r, column=2, sticky="ew", padx=(0, 8), pady=3)
            val = ctk.CTkLabel(wframe, text="\u2013", width=110, anchor="e",
                               font=F(12), text_color=COLOR["ink_soft"])
            val.grid(row=r, column=3, sticky="e")
            self.wrows[key] = {"bar": bar, "val": val, "name": name}

        note = ctk.CTkLabel(s, text="Fonts & page-content optimization arrive in v2 "
                                    "(shown for analysis only).",
                            font=F(11), text_color=COLOR["ink_soft"])
        note.grid(row=2, column=0, sticky="w", padx=18)

        # ---- image quality slider + target ----
        q = ctk.CTkFrame(s, fg_color="transparent")
        q.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 2))
        q.grid_columnconfigure(1, weight=1)
        self._label(q, "Image quality").grid(row=0, column=0, sticky="w")
        self.v_q = ctk.IntVar(value=self.cfg["img_quality"])
        self.lbl_q = ctk.CTkLabel(q, text=str(self.cfg["img_quality"]), width=30,
                                  font=F(13, "bold"), text_color=COLOR["bolt"])
        self.lbl_q.grid(row=0, column=2, padx=(6, 0))
        self._quality_slider = ctk.CTkSlider(
            q, from_=MIN_QUALITY, to=MAX_QUALITY,
            number_of_steps=MAX_QUALITY - MIN_QUALITY, variable=self.v_q,
            progress_color=COLOR["bolt"], button_color=COLOR["bolt"],
            button_hover_color=COLOR["bolt_hover"], fg_color=COLOR["track"],
            command=self._q_moved)
        self._quality_slider.grid(row=0, column=1, sticky="ew", padx=8)

        self._label(q, "Max DPI").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.v_dpi = ctk.StringVar(
            value=str(self.cfg["max_dpi"]) if self.cfg["max_dpi"] else "off")
        self._dpi_menu = ctk.CTkOptionMenu(
            q, values=["off"] + [str(d) for d in DPI_CHOICES],
            variable=self.v_dpi, width=90,
            command=lambda _v: self._refresh_estimate(),
            fg_color=COLOR["card"], text_color=COLOR["ink"],
            button_color=COLOR["bolt"],
            button_hover_color=COLOR["bolt_hover"],
            dropdown_fg_color=COLOR["card"],
            dropdown_text_color=COLOR["ink"], font=F(12),
            corner_radius=8)
        self._dpi_menu.grid(row=1, column=1, sticky="w", padx=8, pady=(6, 0))
        self.v_gray = ctk.BooleanVar(value=self.cfg["grayscale"])
        self._gray_check = ctk.CTkCheckBox(
            q, text="Grayscale images", variable=self.v_gray,
            command=self._refresh_estimate, font=F(12),
            text_color=COLOR["ink"], fg_color=COLOR["bolt"],
            hover_color=COLOR["bolt_hover"], border_color=COLOR["track"],
            checkmark_color="#FFFFFF")
        self._gray_check.grid(row=1, column=1, sticky="e", pady=(6, 0))

        self._label(q, "Target size (KB)").grid(row=2, column=0, sticky="w", pady=6)
        self.v_kb = ctk.StringVar(value=str(self.cfg["target_kb"] or ""))
        self.v_kb.trace_add("write", lambda *_a: self._refresh_estimate())
        self._kb_entry = ctk.CTkEntry(
            q, textvariable=self.v_kb, placeholder_text="optional, e.g. 250",
            width=140, fg_color=COLOR["bolt_soft"],
            border_color=COLOR["card_border"], text_color=COLOR["ink"],
            placeholder_text_color=COLOR["ink_soft"], font=F(13),
            corner_radius=8, border_width=1)
        self._kb_entry.grid(row=2, column=1, sticky="w", padx=8, pady=6)

        self.lbl_est = ctk.CTkLabel(s, text="", font=F(12, "bold"),
                                    text_color=COLOR["green"])
        self.lbl_est.grid(row=4, column=0, sticky="w", padx=18, pady=(0, 12))

    def _build_bulk_panel(self, b):
        b.grid_columnconfigure(1, weight=1)
        self._label(b, "Preset for all files").grid(row=0, column=0, sticky="w",
                                                    padx=(16, 6), pady=14)
        self.v_bulk_preset = ctk.StringVar(
            value=self.cfg.get("bulk_preset", "Balanced (recommended)"))
        ctk.CTkOptionMenu(b, values=list(cfgmod.PRESETS),
                          variable=self.v_bulk_preset, width=260,
                          fg_color=COLOR["bolt"], button_color=COLOR["bolt_hover"],
                          button_hover_color=COLOR["bolt_hover"],
                          dropdown_fg_color=COLOR["card"],
                          dropdown_text_color=COLOR["ink"], font=F(13),
                          corner_radius=8).grid(row=0, column=1, sticky="w", pady=14)
        ctk.CTkLabel(b, text="Every dropped PDF is optimized with this preset, "
                             "one after another.",
                     font=F(11), text_color=COLOR["ink_soft"]
                     ).grid(row=1, column=0, columnspan=2, sticky="w",
                            padx=16, pady=(0, 12))

    # ------------------------------------------------------------- behaviors
    def _mode_changed(self):
        single = self.v_mode.get() == "SINGLE"
        if single:
            self.panel_bulk.grid_forget()
            self.panel_single.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")
            if len(self.files) > 1:
                self.files = self.files[:1]
                self._render_files()
            self._maybe_analyze()
        else:
            self.panel_single.grid_forget()
            self.panel_bulk.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")
            self.status.configure(text=f"{len(self.files)} file(s) queued."
                                  if self.files else
                                  "Drop PDFs above, pick a preset, hit Optimize.")

    def _set_phases(self, on: bool):
        for v in self.v_ph.values():
            v.set(on)
        self._refresh_estimate()

    def _apply_preset(self):
        p = cfgmod.PRESETS.get(self.v_preset.get(), {})
        self.v_reduction_mode = p.get("reduction_mode")
        reduction = self.v_reduction_mode is not None

        # Keep-only modes ignore phases/quality/DPI/target entirely - they
        # rebuild the document from scratch. Grey out those controls so the
        # panel doesn't lie about what will happen.
        state = "disabled" if reduction else "normal"
        for cb in self._phase_checkboxes:
            cb.configure(state=state)
        self._quality_slider.configure(state=state)
        self._dpi_menu.configure(state=state)
        self._gray_check.configure(state=state)
        self._kb_entry.configure(state=state)

        if not reduction:
            self.v_ph["structure"].set(p.get("do_structure", True))
            self.v_ph["metadata"].set(p.get("do_metadata", True))
            self.v_ph["images"].set(p.get("do_images", True))
            self.v_q.set(p.get("img_quality", 75))
            self.lbl_q.configure(text=str(p.get("img_quality", 75)))
            self.v_dpi.set(str(p["max_dpi"]) if p.get("max_dpi") else "off")
            self.v_gray.set(p.get("grayscale", False))
            self.v_kb.set(str(p["target_kb"]) if p.get("target_kb") else "")
        self._refresh_estimate()

    def _q_moved(self, v):
        self.lbl_q.configure(text=str(int(float(v))))
        self._refresh_estimate()

    def _gui_options(self, bulk: bool = False) -> Options:
        if bulk:
            return cfgmod.to_options(self.cfg, preset=self.v_bulk_preset.get())
        if getattr(self, "v_reduction_mode", None):
            return Options(reduction_mode=self.v_reduction_mode,
                          output_dir=self.cfg["output_dir"])
        kb = None
        try:
            kb = int(self.v_kb.get()) if self.v_kb.get().strip() else None
        except ValueError:
            kb = None
        dpi = None if self.v_dpi.get() == "off" else int(self.v_dpi.get())
        return Options(
            do_structure=self.v_ph["structure"].get(),
            do_metadata=self.v_ph["metadata"].get(),
            do_images=self.v_ph["images"].get(),
            img_quality=int(self.v_q.get()),
            max_dpi=dpi, grayscale=self.v_gray.get(),
            target_kb=kb, output_dir=self.cfg["output_dir"],
        )

    # ------------------------------------------------------- files / analyze
    def add_files(self, paths: list[str]):
        single = self.v_mode.get() == "SINGLE"
        pdfs = [p for p in paths if Path(p).suffix.lower() in PDF_EXT]
        imgs = [p for p in paths if Path(p).suffix.lower() in IMAGE_EXT]
        skipped = len(paths) - len(pdfs) - len(imgs)
        if imgs and not pdfs:
            # convenience: dropping images offers Combine-to-PDF
            self._run_thread(lambda: [images_to_pdf(imgs)], verb="combined")
            return
        if single:
            self.files = pdfs[:1]
            if len(pdfs) > 1:
                self.status.configure(
                    text="SINGLE mode takes one PDF - switch to BULK for many.")
        else:
            known = set(self.files)
            self.files += [p for p in pdfs if p not in known]
        if skipped:
            self.status.configure(text=f"{skipped} non-PDF file(s) skipped.")
        self._render_files()
        self._maybe_analyze()

    def _render_files(self):
        self.filebox.configure(state="normal")
        self.filebox.delete("1.0", "end")
        if self.files:
            for p in self.files:
                sz = Path(p).stat().st_size if Path(p).exists() else 0
                self.filebox.insert("end", f"{Path(p).name}   ({_fmt_bytes(sz)})\n")
        else:
            self.filebox.insert("end", "Drop PDF files here...")
        self.filebox.configure(state="disabled")

    def _maybe_analyze(self):
        if self.v_mode.get() != "SINGLE" or not self.files:
            return
        path = self.files[0]
        self.status.configure(text=f"Analyzing {Path(path).name}...")

        def work():
            ana = analyze(path)
            self.events.put(("analysis", ana))
        threading.Thread(target=work, daemon=True).start()

    def _show_analysis(self, ana: Analysis):
        self.analysis = ana
        if not ana.ok:
            self.status.configure(text=f"Cannot analyze: {ana.error}")
            for key, _ in CATEGORIES:
                self.wrows[key]["bar"].set(0)
                self.wrows[key]["val"].configure(text="\u2013")
            self.lbl_est.configure(text="")
            return
        for key, _ in CATEGORIES:
            frac = ana.pct(key) / 100
            self.wrows[key]["bar"].set(frac)
            self.wrows[key]["val"].configure(
                text=f"{_fmt_bytes(ana.breakdown.get(key, 0))}  ({ana.pct(key):.0f}%)")
        self.status.configure(
            text=f"{Path(ana.path).name}: {_fmt_bytes(ana.file_bytes)}, "
                 f"{ana.pages} page(s). Untick phases you want to keep.")
        self._refresh_estimate()

    def _refresh_estimate(self):
        if self.v_mode.get() != "SINGLE" or not self.analysis or not self.analysis.ok:
            return
        if getattr(self, "v_reduction_mode", None):
            if self.v_reduction_mode == "text_vectors":
                msg = ("Keep only Text and Vectors: every image is removed; "
                       "text, vector art, fonts and annotations stay as-is. "
                       f"Apx. output: {_fmt_bytes(self.analysis.non_image_bytes())} or less.")
            else:
                msg = ("Keep only Text: the page is rebuilt from its text alone, "
                       "redrawn in a standard font at the original positions. "
                       "Images, vectors, annotations and metadata are all removed. "
                       "Works best for Latin-script text; non-Latin characters "
                       "(e.g. Chinese, Arabic, Cyrillic) will show as '?'.")
            self.lbl_est.configure(text=msg, text_color=COLOR["ink_soft"])
            return
        opts = self._gui_options()
        est_b, est_s = estimate(self.analysis, opts)
        txt = f"Apx. output: {_fmt_bytes(est_b)}   |   apx. time: "
        txt += f"{est_s:.0f}s" if est_s >= 1 else "<1s"
        if opts.target_kb:
            feasible, floor = self.analysis.target_feasible(opts.target_kb)
            if not feasible:
                txt = (f"Target {opts.target_kb}KB looks below this PDF's floor "
                       f"(~{floor}KB) - best effort will apply.")
                self.lbl_est.configure(text=txt, text_color=COLOR["red"])
                return
            txt = f"Target {opts.target_kb}KB is achievable (floor ~{floor}KB). " \
                  f"Apx. time: {max(1, est_s):.0f}s"
        self.lbl_est.configure(text=txt, text_color=COLOR["green"])

    # ---------------------------------------------------------------- events
    def browse(self):
        from tkinter import filedialog
        multi = self.v_mode.get() == "BULK"
        if multi:
            paths = filedialog.askopenfilenames(
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
            paths = list(paths)
        else:
            p = filedialog.askopenfilename(
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
            paths = [p] if p else []
        if paths:
            self.add_files(paths)

    def clear(self):
        self.files = []
        self.analysis = None
        self._render_files()
        for key, _ in CATEGORIES:
            self.wrows[key]["bar"].set(0)
            self.wrows[key]["val"].configure(text="\u2013")
        self.lbl_est.configure(text="")
        self.status.configure(text="Cleared.")

    def _on_drop(self, event):
        self.add_files(_parse_dropped(event.data))

    def save_defaults(self):
        o = self._gui_options()
        self.cfg.update(dict(
            do_structure=o.do_structure, do_metadata=o.do_metadata,
            do_images=o.do_images, img_quality=o.img_quality,
            max_dpi=o.max_dpi, grayscale=o.grayscale, target_kb=o.target_kb,
            bulk_preset=self.v_bulk_preset.get()
            if self.v_mode.get() == "BULK" else self.v_preset.get(),
        ))
        if cfgmod.save(self.cfg):
            self.status.configure(text="Defaults saved.")

    # ------------------------------------------------------------- optimize
    def optimize(self):
        if self.running:
            return
        if not self.files:
            self.status.configure(text="Add at least one PDF first.")
            return
        bulk = self.v_mode.get() == "BULK"
        opts = self._gui_options(bulk=bulk)
        files = list(self.files)
        self.running = True
        self.btn_go.configure(state="disabled", text="Working...")
        self.bar.set(0)

        def work():
            def per_file(done, total, r: Result):
                self.events.put(("progress", (done, total, r)))
            results = process_batch(files, opts, progress=per_file)
            self.events.put(("done", results))
        threading.Thread(target=work, daemon=True).start()

    def _run_thread(self, job, verb="processed"):
        """Generic runner for the image-drop convenience path."""
        if self.running:
            return
        self.running = True
        self.btn_go.configure(state="disabled", text="Working...")

        def work():
            results = job()
            self.events.put(("done", results))
        threading.Thread(target=work, daemon=True).start()

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "analysis":
                    self._show_analysis(payload)
                elif kind == "progress":
                    done, total, r = payload
                    self.bar.set(done / total)
                    self.status.configure(text=r.summary())
                elif kind == "done":
                    results: list[Result] = payload
                    self.running = False
                    self.btn_go.configure(state="normal", text="Optimize")
                    self.bar.set(1 if results else 0)
                    ok = [r for r in results if r.ok]
                    bad = [r for r in results if not r.ok]
                    unmet = [r for r in ok if r.target_kb and not r.target_met]
                    non_latin = [r for r in ok if getattr(r, "non_latin_detected", False)]
                    if len(results) == 1:
                        self.status.configure(text=results[0].summary())
                    else:
                        saved = sum(r.in_bytes - r.out_bytes for r in ok)
                        msg = f"Done: {len(ok)} ok, {len(bad)} failed, " \
                              f"{_fmt_bytes(max(0, saved))} saved."
                        if unmet:
                            msg += f" ({len(unmet)} reached their size floor.)"
                        if non_latin:
                            msg += f" ({len(non_latin)} had non-Latin text replaced with '?'.)"
                        self.status.configure(text=msg)
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    # ----------------------------------------------------------------- about
    def show_about(self):
        from .__init__ import __version__
        import webbrowser

        top = ctk.CTkToplevel(self.root, fg_color=COLOR["bg"])
        top.title("About SnapPDF")
        top.geometry("440x500")
        top.resizable(False, False)
        top.transient(self.root)
        top.after(100, lambda: top.grab_set())

        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 440) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 500) // 2
        top.geometry(f"+{max(0, x)}+{max(0, y)}")

        wrap = ctk.CTkFrame(top, corner_radius=0, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=30, pady=28)

        ctk.CTkLabel(wrap, text="\u26a1", font=F(30),
                     text_color=COLOR["bolt"]).pack(pady=(0, 4))
        ctk.CTkLabel(wrap, text="SnapPDF", font=F(26, "bold"),
                     text_color=COLOR["ink"]).pack(pady=(0, 2))
        ctk.CTkLabel(wrap, text=f"v{__version__}  \u00b7  Tool #2 of the Snap series",
                     font=F(12), text_color=COLOR["ink_soft"]).pack(pady=(0, 18))

        ctk.CTkLabel(wrap, text="Developed by", font=F(12),
                     text_color=COLOR["ink_soft"]).pack(pady=(0, 4))
        ctk.CTkLabel(wrap, text="VIJAY PARMAR", font=F(22, "bold"),
                     text_color=COLOR["ink"]).pack(pady=(0, 18))

        badges = ctk.CTkFrame(wrap, fg_color="transparent")
        badges.pack(pady=(0, 22))
        for text in ("Open Source", "Free Forever"):
            ctk.CTkLabel(badges, text=text, font=F(12, "bold"),
                         fg_color=COLOR["bolt_soft"],
                         text_color=COLOR["bolt_hover"],
                         corner_radius=100, padx=14, pady=6
                         ).pack(side="left", padx=6)

        LINKS = [
            ("GitHub", "https://github.com/vijayparmar"),
            ("LinkedIn", "https://www.linkedin.com/in/vijayparmar"),
        ]
        for label, url in LINKS:
            lk = ctk.CTkLabel(wrap, text=label, font=F(13, "bold"),
                              text_color=COLOR["bolt"], cursor="hand2")
            lk.pack(pady=2)
            lk.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))

        ctk.CTkLabel(wrap, text="MIT License \u00b7 fully offline \u00b7 "
                                "originals are never modified",
                     font=F(11), text_color=COLOR["ink_soft"]).pack(pady=(18, 0))


def launch(files: list[str] | None = None) -> None:
    app = SnapPDFApp(files)
    app.root.mainloop()
