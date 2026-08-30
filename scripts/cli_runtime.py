"""Shared command-line runtime behavior for the Skill."""
from __future__ import annotations

import sys


def configure_utf8_stdio() -> None:
    """Make JSON and Chinese text stable across Windows console code pages."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            pass
