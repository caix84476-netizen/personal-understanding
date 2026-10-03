#!/usr/bin/env python3
"""Single source of truth for record schema constraints (2.7.0).

Before this module the MCP write path and the validate_memory auditor disagreed:
add_record accepted domain values the auditor then rejected ("learning" vs the
branch id "domain.learning-interests") — a write-then-die trap — accepted
out-of-range salience for full-tier records, and wrote unparsable dates that
silently degraded to "undated" downstream. Both sides now read the constants
and helpers here. Dependency-light by design: stdlib only, no catalog_utils
import (which would drag in the lexicon machinery).
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

VALID_KINDS = frozenset({"fact", "state", "event", "preference", "rule", "heuristic", "value", "decision", "model", "entity"})
VALID_SENSITIVITY = frozenset({"ordinary", "private", "highly-private"})
VALID_CONFIDENCE = frozenset({"high", "medium-high", "medium", "low", "very-high", "low-medium"})
ROUTING_KINDS = frozenset({"state", "decision", "model", "value", "heuristic", "rule", "preference"})
SALIENCE_MAX = 3

DATE_DAY_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
DATE_MONTH_RE = re.compile(r"20\d{2}-\d{2}")
DATE_YEAR_RE = re.compile(r"20\d{2}")
DATE_FORMAT_HINT = "YYYY-MM-DD / YYYY-MM / YYYY"


def branch_ids(root: Path) -> set[str]:
    """Legal domain values are the frontmatter ids of memory/branches/*.md —
    the same definition validate_memory audits against."""
    ids: set[str] = set()
    branches = root / "memory" / "branches"
    if not branches.is_dir():
        return ids
    for path in sorted(branches.glob("*.md")):
        if path.name == "index.md":
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if not lines or lines[0].strip() != "---":
            continue
        for line in lines[1:]:
            stripped = line.strip()
            if stripped == "---":
                break
            if stripped.startswith("id:"):
                value = stripped.split(":", 1)[1].strip()
                if value:
                    ids.add(value)
                break
    return ids


def valid_date_string(value: object) -> bool:
    """True only for a well-formed *calendar* date the archive understands.

    parse_date_value used to accept "2026-13-99" verbatim; downstream the v2
    projection then treated the record as undated and recency as neutral — the
    date silently meant nothing. Month/day components are now range-checked and
    day precision must construct a real date."""
    raw = str(value if value is not None else "").strip()
    if DATE_DAY_RE.fullmatch(raw):
        try:
            date(int(raw[:4]), int(raw[5:7]), int(raw[8:10]))
        except ValueError:
            return False
        return True
    if DATE_MONTH_RE.fullmatch(raw):
        return 1 <= int(raw[5:7]) <= 12
    return bool(DATE_YEAR_RE.fullmatch(raw))
