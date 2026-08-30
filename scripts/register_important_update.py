#!/usr/bin/env python3
"""Increment important updates and emit an automatic deep-review execution alert when due."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

from datetime import date
from pathlib import Path
import subprocess
import sys
import argparse
import json

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "memory" / "review-state.json"
IMMEDIATE_REASONS = {"correction", "attribution", "privacy", "structure", "compression", "decision"}
DEFAULT_REVIEW_THRESHOLD = 8


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", default="")
    parser.add_argument("--reason", choices=sorted(IMMEDIATE_REASONS), help="immediate deep-review trigger reason")
    args = parser.parse_args()
    try:
        data = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data["review_threshold"] = int(data.get("review_threshold", DEFAULT_REVIEW_THRESHOLD))
    data["important_updates_since_review"] = int(data.get("important_updates_since_review", 0)) + 1
    data["last_update_on"] = date.today().isoformat()
    if args.note:
        data["last_update_note"] = args.note
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    due = data["important_updates_since_review"] >= data["review_threshold"]
    triggered = bool(args.reason or due)
    print(f"Important updates since last review: {data['important_updates_since_review']}/{data['review_threshold']}")
    print("Review due: " + str(due).lower())
    if triggered:
        cycle = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_review_cycle.py"), "--reason", args.reason or "threshold", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if cycle.stdout:
            print(cycle.stdout.strip())
        if cycle.returncode:
            if cycle.stderr:
                print(cycle.stderr.strip(), file=sys.stderr)
            return cycle.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



