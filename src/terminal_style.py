"""Couleurs ANSI pour le terminal (Windows + Unix)."""
from __future__ import annotations

import os
import sys

_USE_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR") is None
    and os.environ.get("TERM") != "dumb"
)


def _enable_windows_ansi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 4)
    except Exception:
        pass


_enable_windows_ansi()


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def color_enabled() -> bool:
    return _USE_COLOR


def set_color_enabled(enabled: bool) -> None:
    global _USE_COLOR
    _USE_COLOR = enabled and sys.stdout.isatty()


def sty(text: str, *codes: str) -> str:
    if not _USE_COLOR or not codes:
        return text
    return "".join(codes) + text + C.RESET
