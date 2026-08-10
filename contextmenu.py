"""
SnapPDF Context Menu - registry-based, same mechanism as SnapShrink.

Lives under "Show more options" on Windows 11 (classic registration) -
the IExplorerCommand/COM top-level route stays deliberately dropped, same
decision as SnapShrink.

Right-click a PDF:
  SnapPDF > Quick Optimize                      (hotkey preset, instant)
          > Shrink to size  > 10KB ... 5MB      (absolute targets)
          > Shrink to %     > 50% ... 95%       (relative to each file)
          > Convert to images > 72 ... 300 DPI
          > Merge PDFs                          (multi-select)
          > Merge & shrink to > 100KB ... 5MB   (multi-select combined action)
          > Open SnapPDF

Right-click image files:
  SnapPDF > Combine to PDF

MULTI-SELECT NOTE (the merge problem): classic registry verbs launch the
command once PER SELECTED FILE. Independent actions (shrink each) are fine
with that. Merge is not - it needs the whole selection in one process. So
the merge handlers in daemon.py use a singleton guard: the first process
grabs a short-lived lock file, queries Explorer for the FULL selection
(SnapShrink's pywin32 trick), and does the merge; the other N-1 processes
see the fresh lock and exit silently.

Install / uninstall:
    python -m sppack --install-contextmenu
    python -m sppack --uninstall-contextmenu
(The frozen SnapPDF.exe registers ITSELF - no separate shim.)
"""

from __future__ import annotations

import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# Presets shown in the flyouts (confirmed list from Vijay)
KB_SIZES = [10, 50, 100, 150, 200, 250, 500, 1024, 5120]     # 1024=1MB 5120=5MB
PCT_SIZES = [50, 60, 70, 80, 90, 95]
DPI_SIZES = [72, 120, 150, 200, 300]
MERGE_KB_SIZES = [100, 250, 500, 1024, 5120]

PDF_BASE = r"Software\Classes\SystemFileAssociations\.pdf\shell"
IMG_BASE = r"Software\Classes\SystemFileAssociations\image\shell"


def _kb_label(kb: int) -> str:
    return f"{kb // 1024}MB" if kb >= 1024 else f"{kb}KB"


def _exe() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    # dev fallback: python -m sppack (used only for source-tree testing)
    return Path(sys.executable)


def _cmd(args: str) -> str:
    """Command line for a registry entry. Frozen: the exe itself. Source:
    python -m sppack (with --cwd so the package resolves from Explorer)."""
    exe = _exe()
    if getattr(sys, "frozen", False):
        return f'"{exe}" {args}'
    pkg_parent = Path(__file__).resolve().parent.parent
    return f'"{exe}" -m sppack --cwd "{pkg_parent}" {args}'


def install(shim_exe=None) -> int:
    if not IS_WINDOWS:
        print("Windows only.")
        return 1
    import winreg

    icon = str(_exe())

    def setval(path, name, value):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    try:
        top = f"{PDF_BASE}\\SnapPDF"
        setval(top, "MUIVerb", "SnapPDF")
        setval(top, "Icon", icon)
        setval(top, "subcommands", "")
        setval(top, "MultiSelectModel", "Player")

        # --- 1. Quick Optimize (hotkey preset) ---
        k = f"{top}\\shell\\01quick"
        setval(k, "MUIVerb", "Quick Optimize")
        setval(k, "Icon", icon)
        setval(f"{k}\\command", "", _cmd('--quick "%1"'))

        # --- 2. Shrink to size ---
        k = f"{top}\\shell\\02size"
        setval(k, "MUIVerb", "Shrink to size")
        setval(k, "Icon", icon)
        setval(k, "subcommands", "")
        for i, kb in enumerate(KB_SIZES):
            kk = f"{k}\\shell\\s{i:02d}_{kb}"
            setval(kk, "MUIVerb", _kb_label(kb))
            setval(f"{kk}\\command", "", _cmd(f'--ctx-size {kb} "%1"'))

        # --- 3. Shrink to % of file size ---
        k = f"{top}\\shell\\03pct"
        setval(k, "MUIVerb", "Shrink to % of size")
        setval(k, "Icon", icon)
        setval(k, "subcommands", "")
        for i, pc in enumerate(PCT_SIZES):
            kk = f"{k}\\shell\\p{i:02d}_{pc}"
            setval(kk, "MUIVerb", f"{pc}%")
            setval(f"{kk}\\command", "", _cmd(f'--ctx-pct {pc} "%1"'))

        # --- 4. Convert to images ---
        k = f"{top}\\shell\\04toimg"
        setval(k, "MUIVerb", "Convert to images")
        setval(k, "Icon", icon)
        setval(k, "subcommands", "")
        for i, dpi in enumerate(DPI_SIZES):
            kk = f"{k}\\shell\\d{i:02d}_{dpi}"
            setval(kk, "MUIVerb", f"{dpi} DPI")
            setval(f"{kk}\\command", "", _cmd(f'--ctx-toimages {dpi} "%1"'))

        # --- 5. Merge PDFs (multi-select; singleton guard in daemon) ---
        k = f"{top}\\shell\\05merge"
        setval(k, "MUIVerb", "Merge PDFs")
        setval(k, "Icon", icon)
        setval(f"{k}\\command", "", _cmd('--ctx-merge "%1"'))

        # --- 6. Merge & shrink to ---
        k = f"{top}\\shell\\06mergesize"
        setval(k, "MUIVerb", "Merge && shrink to")
        setval(k, "Icon", icon)
        setval(k, "subcommands", "")
        for i, kb in enumerate(MERGE_KB_SIZES):
            kk = f"{k}\\shell\\m{i:02d}_{kb}"
            setval(kk, "MUIVerb", _kb_label(kb))
            setval(f"{kk}\\command", "", _cmd(f'--ctx-mergesize {kb} "%1"'))

        # --- 7. Open SnapPDF ---
        k = f"{top}\\shell\\07open"
        setval(k, "MUIVerb", "Open SnapPDF")
        setval(k, "Icon", icon)
        setval(f"{k}\\command", "", _cmd('"%1"'))

        # --- 8. Keep only Text and Vectors (strip images) ---
        k = f"{top}\\shell\\08textvec"
        setval(k, "MUIVerb", "Keep only Text and Vectors")
        setval(k, "Icon", icon)
        setval(f"{k}\\command", "", _cmd('--ctx-textvectors "%1"'))

        # --- 9. Keep only Text (extract + redraw, base-14 fonts) ---
        k = f"{top}\\shell\\09textonly"
        setval(k, "MUIVerb", "Keep only Text")
        setval(k, "Icon", icon)
        setval(f"{k}\\command", "", _cmd('--ctx-textonly "%1"'))

        # ============ image files: Combine to PDF ============
        itop = f"{IMG_BASE}\\SnapPDF"
        setval(itop, "MUIVerb", "SnapPDF")
        setval(itop, "Icon", icon)
        setval(itop, "subcommands", "")
        setval(itop, "MultiSelectModel", "Player")
        k = f"{itop}\\shell\\01imgs2pdf"
        setval(k, "MUIVerb", "Combine to PDF")
        setval(f"{k}\\command", "", _cmd('--ctx-imgs2pdf "%1"'))

        print("SnapPDF context menu installed (current user only).")
        print(f"  PDF entries:   HKCU\\{PDF_BASE}\\SnapPDF")
        print(f"  Image entries: HKCU\\{IMG_BASE}\\SnapPDF")
        return 0
    except Exception as e:
        print(f"Install failed: {e}")
        return 1


def uninstall() -> int:
    if not IS_WINDOWS:
        print("Windows only.")
        return 1
    import winreg

    def nuke(path: str):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                                winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        child = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    nuke(f"{path}\\{child}")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"  Could not remove {path}: {e}")

    nuke(f"{PDF_BASE}\\SnapPDF")
    nuke(f"{IMG_BASE}\\SnapPDF")
    print("SnapPDF context menu removed.")
    return 0
