"""Keep every Skill CLI machine-readable on Windows and Unix terminals."""
from __future__ import annotations

import sys

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, OSError):
        pass
