#!/usr/bin/env python3
"""Quarterly salience review: propose and apply memory-weight decay.

The archive only grows. Entries whose weight was imported by heuristic and
that have not been confirmed for a long time gradually overstate their
current value to understanding the user. This script:

1. lists current records with no explicit `salience` in frontmatter whose
   last confirmation is older than --min-age-days (default 180);
2. dry-run prints the proposal; --apply writes an explicit `salience: 0`
   plus `salience_reviewed` date into frontmatter (never deletes content).

Weight 0 (`passing`) means "kept, retrievable, but not part of the active map".
Nothing is deleted or rewritten; a later user mention can re-raise it.
"""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
import re
from datetime import date
from pathlib import Path

from catalog_utils import ROOT

DEFAULT_MIN_AGE_DAYS = 180
REVIEWABLE_KINDS = {"event", "fact", "entity"}


def _frontmatter_span(text: str) -> tuple[int, int]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return -1, -1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return 0, index + 1
    return -1, -1


def last_confirmed_date(meta: dict[str, str]) -> str | None:
    value = meta.get("last_confirmed") or meta.get("valid_from") or ""
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else None


def candidates(min_age_days: int, root: Path = ROOT) -> list[dict[str, object]]:
    today = date.today()
    rows = []
    records_dir = root / "memory" / "records"
    for path in sorted(records_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta: dict[str, str] = {}
        lines = text.splitlines()
        if lines and lines[0].strip() == "---":
            for line in lines[1:]:
                if line.strip() == "---":
                    break
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip()
        if meta.get("status") != "current" or meta.get("kind") not in REVIEWABLE_KINDS:
            continue
        if meta.get("salience") or meta.get("memory_weight") or meta.get("salience_reviewed"):
            continue  # explicit weight or already reviewed
        confirmed = last_confirmed_date(meta)
        if not confirmed:
            continue
        age = (today - date.fromisoformat(confirmed)).days
        if age >= min_age_days:
            rows.append({"id": meta.get("id"), "kind": meta.get("kind"), "last_confirmed": confirmed, "age_days": age, "path": str(path)})
    return sorted(rows, key=lambda item: -int(item["age_days"]))


def apply_decay(item: dict[str, object], root: Path = ROOT) -> bool:
    """Insert the salience lines inside the frontmatter (before the closing ---).

    Note: _frontmatter_span returns line numbers; operate on lines here,
    never slice by treating line numbers as character offsets (that would
    cut the id line in half).
    """
    path = Path(str(item["path"]))
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return False
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        return False
    eol = "\r\n" if lines[0].endswith("\r\n") else "\n"
    inserted = [f"salience: 0{eol}", f"salience_reviewed: {date.today().isoformat()}{eol}"]
    new_lines = lines[:closing] + inserted + lines[closing:]
    path.write_text("".join(new_lines), encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-age-days", type=int, default=DEFAULT_MIN_AGE_DAYS)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = candidates(args.min_age_days)
    if args.json:
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "candidates": len(rows), "items": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"Salience review ({'apply' if args.apply else 'dry-run'}): {len(rows)} candidates for decay")
        for item in rows[:40]:
            print(f"- `{item['id']}` [{item['kind']}] last confirmed {item['last_confirmed']} ({item['age_days']} days)")
        if not args.apply:
            print("Dry run: no files modified; rerun with --apply to confirm. Decay only writes salience: 0 (passing level); no content is deleted.")
    if args.apply:
        done = sum(1 for item in rows if apply_decay(item))
        print(f"Decayed {done} record(s) and wrote the salience_reviewed date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
