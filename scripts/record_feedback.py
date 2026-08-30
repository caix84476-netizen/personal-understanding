#!/usr/bin/env python3
"""Record answer-quality feedback so the archive learns which memories help.

After an answer that leaned on personal memory, the model appends one row:
which capture/turn, which memory IDs it used, and what the user's natural
reaction showed (helpful / missed / corrected). No formal user rating is
required; a user correction is the strongest signal.

Rows go to memory/v2/feedback.jsonl. review_v2.py aggregates miss/correction
streaks per memory id so recurring misses surface during deep review.
"""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
from datetime import datetime
from pathlib import Path

from catalog_utils import ROOT
from derivation_ledger import ID_RE

FEEDBACK = ROOT / "memory" / "v2" / "feedback.jsonl"
VALID_OUTCOMES = {"helpful", "missed", "corrected", "unclear"}


def read_feedback(path: Path = FEEDBACK) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def miss_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    tally: dict[str, int] = {}
    for row in rows:
        if row.get("outcome") in {"missed", "corrected"}:
            for memory_id in row.get("memory_ids_used", []) or []:
                tally[str(memory_id)] = tally.get(str(memory_id), 0) + 1
    ranked = sorted(tally.items(), key=lambda pair: -pair[1])
    return {
        "total_feedback": len(rows),
        "helpful": sum(1 for row in rows if row.get("outcome") == "helpful"),
        "missed_or_corrected": sum(1 for row in rows if row.get("outcome") in {"missed", "corrected"}),
        "worst_memory_ids": [{"id": memory_id, "miss_count": count} for memory_id, count in ranked[:12]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feedback-id", default="")
    ap.add_argument("--capture-id", default="")
    ap.add_argument("--memory-ids", default="", help="memory IDs actually used in this answer, comma/semicolon separated")
    ap.add_argument("--outcome", choices=sorted(VALID_OUTCOMES), default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--summary", action="store_true", help="print the feedback summary only, without writing")
    args = ap.parse_args()
    rows = read_feedback()
    if args.summary:
        print(json.dumps(miss_summary(rows), ensure_ascii=False, indent=2))
        return 0
    if not args.feedback_id or not args.outcome:
        raise SystemExit("Writing feedback requires --feedback-id and --outcome; use --summary to view the summary only.")
    if not ID_RE.fullmatch(args.feedback_id):
        raise SystemExit("Invalid feedback-id.")
    if any(row.get("id") == args.feedback_id for row in rows):
        raise SystemExit(f"Refusing to overwrite existing feedback: {args.feedback_id}")
    memory_ids = [item.strip() for item in args.memory_ids.replace(";", ",").split(",") if item.strip()]
    row = {
        "id": args.feedback_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "capture_id": args.capture_id or None,
        "memory_ids_used": memory_ids,
        "outcome": args.outcome,
        "note": args.note,
    }
    FEEDBACK.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"status": "recorded", "row": row, "summary": miss_summary(rows + [row])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
