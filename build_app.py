#!/usr/bin/env python3
"""
Build SnapPDF.exe (the whole app: window, daemon, hotkey, right-click).

Run from the snappdf folder (the one with 'sppack' inside it):

    python installer\\build_app.py

Produces:  installer\\dist\\SnapPDF\\SnapPDF.exe  (plus support files)

Same decisions as SnapShrink, kept deliberately:
  * --onedir, NOT --onefile: onefile unpacks to temp on every launch and
    kills the "right-click feels instant" promise.
  * NO sys.path.insert of a raw filesystem path in the entry script - it
    breaks stdlib resolution in the frozen exe. --paths (build-time only)
    is the correct mechanism.
  * --collect-all ONLY for packages proven to need it (they hide data
    files from PyInstaller). Each unnecessary --collect-all silently
    balloons the installer.

NEW for SnapPDF: a size audit at the end. pikepdf ships qpdf DLLs and
pypdfium2 ships pdfium.dll - together roughly +8-12 MB over SnapShrink's
folder. The audit prints the biggest files so a surprise heavyweight
dependency gets caught BEFORE it reaches users.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent      # .../snappdf/installer
ROOT = HERE.parent                          # .../snappdf

# SnapShrink's dist folder was ~45 MB; SnapPDF's is expected around 55-65 MB.
# Anything past this threshold means an accidental heavy import sneaked in.
SIZE_WARN_MB = 80


def fail(msg: str, fix: str = "") -> int:
    print("\n" + "!" * 60)
    print("BUILD FAILED: " + msg)
    if fix:
        print("\nHOW TO FIX:\n" + fix)
    print("!" * 60)
    return 1


def main() -> int:
    print("=" * 60)
    print(" Building SnapPDF.exe (the full app)")
    print("=" * 60)
    print(f"Python being used : {sys.executable}")
    print(f"SnapPDF folder    : {ROOT}")

    if not (ROOT / "sppack" / "__main__.py").exists():
        return fail("Can't find the 'sppack' folder next to 'installer'.",
                    f"Run this script from snappdf\\installer. Current: {HERE}")

    probe = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        return fail("PyInstaller is not installed for this Python.",
                    f'  "{sys.executable}" -m pip install pyinstaller')
    print(f"PyInstaller       : {probe.stdout.strip()} OK")

    entry = HERE / "_entry.py"
    entry.write_text(
        # Clean frozen entry point - no path hacking (see module docstring).
        "from sppack.__main__ import main\n"
        "import sys\n"
        "sys.exit(main())\n",
        encoding="utf-8",
    )

    dist = HERE / "dist"
    work = HERE / "build"
    icon = ROOT / "snappdf.ico"     # optional; default icon if missing

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--noconsole",
        "--noconfirm",
        "--clean",
        "--name", "SnapPDF",
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(work),
        "--paths", str(ROOT),               # build-time package discovery only
        # proven-needed data collection (same three as SnapShrink):
        "--collect-all", "customtkinter",
        "--collect-all", "tkinterdnd2",
        "--collect-all", "winotify",
        # pikepdf/pypdfium2 declare their binaries correctly - PyInstaller's
        # hooks pick up qpdf + pdfium DLLs WITHOUT --collect-all. Do not add
        # --collect-all for them unless a missing-DLL error proves the need.
        "--hidden-import", "win32timezone",  # pywin32 quirk, harmless if unused
    ]
    if icon.exists():
        cmd += ["--icon", str(icon)]
    cmd.append(str(entry))

    print("\nRunning PyInstaller (1-3 minutes)...\n")
    result = subprocess.run(cmd)
    entry.unlink(missing_ok=True)

    if result.returncode != 0:
        return fail("PyInstaller reported an error (scroll up).")

    exe = dist / "SnapPDF" / "SnapPDF.exe"
    if not exe.exists():
        return fail(f"Build finished but no exe at:\n  {exe}")

    # ---- size audit ------------------------------------------------------
    folder = dist / "SnapPDF"
    files = sorted(folder.rglob("*"), key=lambda p: p.stat().st_size
                   if p.is_file() else 0, reverse=True)
    total = sum(p.stat().st_size for p in files if p.is_file())
    print("\n" + "=" * 60)
    print(f" DONE - built: {exe}")
    print(f" Folder size : {total/1024/1024:.1f} MB")
    print(" 10 biggest files:")
    shown = 0
    for p in files:
        if p.is_file() and shown < 10:
            print(f"   {p.stat().st_size/1024/1024:6.1f} MB  {p.relative_to(folder)}")
            shown += 1
    if total > SIZE_WARN_MB * 1024 * 1024:
        print(f"\n WARNING: folder exceeds {SIZE_WARN_MB} MB - an unnecessary")
        print(" heavy dependency probably sneaked in. Check the list above")
        print(" before shipping (compare with SnapShrink's ~45 MB).")
    print("=" * 60)
    print("\nNEXT STEP: open installer\\SnapPDF.iss in Inno Setup and")
    print("click Compile (F9). The installer lands in installer\\output\\.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
