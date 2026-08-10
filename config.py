"""
SnapPDF - settings storage.

Same pattern as SnapShrink: config.json lives in the APPLICATION FOLDER
(next to SnapPDF.exe), not AppData, so the install stays portable and
needs no admin. Installer must therefore target a user-writable folder
(Inno Setup: PrivilegesRequired=lowest, {localappdata}\\Programs\\SnapPDF).
Falls back to LocalAppData only if the app folder isn't writable.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------- defaults

DEFAULTS: dict = {
    # --- master settings: SINGLE-mode panel remembers these ---
    "do_structure": True,
    "do_metadata": True,
    "do_images": True,
    "img_quality": 75,
    "max_dpi": None,            # None or 72/120/150/200/300
    "grayscale": False,
    "linearize": False,
    "target_kb": None,
    "output_dir": None,

    # --- BULK-mode preset name (from PRESETS below) ---
    "bulk_preset": "Balanced (recommended)",

    # --- hotkey preset: Ctrl+Alt+P quick-optimize (independent of above)
    #     Vijay's spec: Structure + Metadata + Invisible + Fonts(v2) +
    #     Images up to 75%. v1 runs the phases that exist. ---
    "hotkey_enabled": True,
    "hotkey": "<ctrl>+<alt>+p",
    "hk_do_structure": True,
    "hk_do_metadata": True,
    "hk_do_images": True,
    "hk_img_quality": 75,
    "hk_grayscale": False,

    # --- feedback ---
    "toast_feedback": True,
    "sound_feedback": True,
    "progress_window": True,    # floating non-disturbing progress for ctx ops
}

# GUI preset dropdown (SINGLE + BULK). Each maps onto Options fields.
PRESETS: dict[str, dict] = {
    "Balanced (recommended)": dict(do_structure=True, do_metadata=True,
                                   do_images=True, img_quality=75,
                                   max_dpi=None, grayscale=False),
    "Maximum compression":    dict(do_structure=True, do_metadata=True,
                                   do_images=True, img_quality=45,
                                   max_dpi=150, grayscale=False),
    "Lossless only":          dict(do_structure=True, do_metadata=True,
                                   do_images=False, img_quality=90,
                                   max_dpi=None, grayscale=False),
    "Email (target 1 MB)":    dict(do_structure=True, do_metadata=True,
                                   do_images=True, img_quality=75,
                                   max_dpi=150, grayscale=False,
                                   target_kb=1024),
    "Upload (target 500 KB)": dict(do_structure=True, do_metadata=True,
                                   do_images=True, img_quality=75,
                                   max_dpi=150, grayscale=False,
                                   target_kb=500),
    "Scan cleanup (grayscale)": dict(do_structure=True, do_metadata=True,
                                     do_images=True, img_quality=65,
                                     max_dpi=200, grayscale=True),
    "Metadata scrub only":    dict(do_structure=False, do_metadata=True,
                                   do_images=False, img_quality=90,
                                   max_dpi=None, grayscale=False),
    "Web (Fast Web View)":    dict(do_structure=True, do_metadata=True,
                                   do_images=True, img_quality=80,
                                   max_dpi=None, grayscale=False,
                                   linearize=True),
    "Keep only Text and Vectors": dict(reduction_mode="text_vectors"),
    "Keep only Text":             dict(reduction_mode="text_only"),
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _fallback_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / "SnapPDF"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    primary = app_dir() / "config.json"
    try:
        probe = app_dir() / ".write_test"
        probe.write_text("x")
        probe.unlink()
        return primary
    except Exception:
        return _fallback_dir() / "config.json"


def load() -> dict:
    cfg = dict(DEFAULTS)
    p = config_path()
    try:
        if p.exists():
            saved = json.loads(p.read_text(encoding="utf-8"))
            for k in DEFAULTS:
                if k in saved:
                    cfg[k] = saved[k]
    except Exception as e:
        print(f"[CONFIG] could not read {p}: {e} - using defaults")
    return cfg


def save(cfg: dict) -> bool:
    p = config_path()
    try:
        clean = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
        p.write_text(json.dumps(clean, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[CONFIG] SAVE FAILED {p}: {e}")
        return False


def to_options(cfg: dict, hotkey_preset: bool = False, preset: str | None = None):
    """Build an engine Options from saved settings, the hotkey preset, or a
    named GUI preset."""
    from .engine import Options
    if preset:
        base = dict(PRESETS.get(preset, PRESETS["Balanced (recommended)"]))
        return Options(
            do_structure=base.get("do_structure", True),
            do_metadata=base.get("do_metadata", True),
            do_images=base.get("do_images", True),
            img_quality=base.get("img_quality", 75),
            max_dpi=base.get("max_dpi"),
            grayscale=base.get("grayscale", False),
            linearize=base.get("linearize", False),
            target_kb=base.get("target_kb"),
            reduction_mode=base.get("reduction_mode"),
        )
    if hotkey_preset:
        return Options(
            do_structure=cfg["hk_do_structure"],
            do_metadata=cfg["hk_do_metadata"],
            do_images=cfg["hk_do_images"],
            img_quality=cfg["hk_img_quality"],
            grayscale=cfg["hk_grayscale"],
        )
    return Options(
        do_structure=cfg["do_structure"], do_metadata=cfg["do_metadata"],
        do_images=cfg["do_images"], img_quality=cfg["img_quality"],
        max_dpi=cfg["max_dpi"], grayscale=cfg["grayscale"],
        linearize=cfg["linearize"], target_kb=cfg["target_kb"],
        output_dir=cfg["output_dir"],
    )
