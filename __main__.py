"""
SnapPDF - single entry point. Decides what to do, then imports ONLY what
that job needs (same rule that keeps SnapShrink's right-click instant:
the ctx/hotkey paths never import customtkinter).

    python -m sppack                        -> window, empty drop zone
    python -m sppack a.pdf                  -> window, file queued (SINGLE mode)
    python -m sppack --quick a.pdf          -> silent optimize, hotkey preset
    python -m sppack --ctx-size 250 a.pdf   -> right-click "Shrink to 250KB"
    python -m sppack --ctx-pct 50 a.pdf     -> right-click "Shrink to 50%"
    python -m sppack --ctx-toimages 150 a.pdf
    python -m sppack --ctx-merge a.pdf      -> merge full Explorer selection
    python -m sppack --ctx-mergesize 500 a.pdf
    python -m sppack --ctx-imgs2pdf a.jpg   -> combine selected images to PDF
    python -m sppack --daemon               -> tray + Ctrl+Alt+P listener
    python -m sppack --install-contextmenu / --uninstall-contextmenu
    python -m sppack --selftest             -> engine test suite
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # --cwd <path>: used by SOURCE-TREE registry commands only, so Python
    # can find the package when launched from Explorer. The frozen exe
    # never needs it (and the entry script never sys.path-hacks - that
    # breaks stdlib resolution in the packaged exe; see build_app.py).
    if "--cwd" in argv:
        i = argv.index("--cwd")
        try:
            sys.path.insert(0, argv[i + 1])
            del argv[i:i + 2]
        except IndexError:
            del argv[i:]

    if "--help" in argv or "-h" in argv or "/?" in argv:
        print(__doc__)
        return 0

    if "--selftest" in argv:
        from .engine import _selftest
        return _selftest()

    if "--install-contextmenu" in argv:
        from .contextmenu import install
        return install()

    if "--uninstall-contextmenu" in argv:
        from .contextmenu import uninstall
        return uninstall()

    def _files(after_flag_index: int) -> list[str]:
        return [a for a in argv[after_flag_index:] if not a.startswith("--")]

    try:
        if "--ctx-size" in argv:
            from .daemon import run_quick
            i = argv.index("--ctx-size")
            run_quick(_files(i + 2), ctx_size_kb=int(argv[i + 1]))
            return 0
        if "--ctx-pct" in argv:
            from .daemon import run_quick
            i = argv.index("--ctx-pct")
            run_quick(_files(i + 2), ctx_pct=int(argv[i + 1]))
            return 0
        if "--ctx-toimages" in argv:
            from .daemon import run_to_images
            i = argv.index("--ctx-toimages")
            run_to_images(int(argv[i + 1]), _files(i + 2))
            return 0
        if "--ctx-merge" in argv:
            from .daemon import run_merge
            run_merge(None)
            return 0
        if "--ctx-mergesize" in argv:
            from .daemon import run_merge
            i = argv.index("--ctx-mergesize")
            run_merge(int(argv[i + 1]))
            return 0
        if "--ctx-imgs2pdf" in argv:
            from .daemon import run_imgs2pdf
            run_imgs2pdf()
            return 0
        if "--ctx-textvectors" in argv:
            from .daemon import run_reduction
            i = argv.index("--ctx-textvectors")
            run_reduction("text_vectors", _files(i + 1))
            return 0
        if "--ctx-textonly" in argv:
            from .daemon import run_reduction
            i = argv.index("--ctx-textonly")
            run_reduction("text_only", _files(i + 1))
            return 0
    except (ValueError, IndexError) as e:
        print(f"[CTX] argument parse error: {e}")
        return 1

    if "--daemon" in argv:
        from .daemon import start
        return start()

    if "--quick" in argv:
        from .daemon import run_quick
        files = [a for a in argv if not a.startswith("--")]
        run_quick(files or None)   # None -> ask Explorer (hotkey path)
        return 0

    # Default: open the window (with any files passed as arguments)
    files = [a for a in argv if not a.startswith("--")]
    from .gui import launch
    launch(files or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
