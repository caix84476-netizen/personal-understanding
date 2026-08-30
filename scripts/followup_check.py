#!/usr/bin/env python3
"""Check pending follow-ups and produce contextual prompts for the model."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()
import argparse, json
from datetime import date, datetime, timedelta
from v2_archive import followup_due_day, followup_open, load_v2


def parse_day(value: str | None) -> date | None:
    if not value: return None
    try: return date.fromisoformat(value[:10])
    except ValueError: return None


def check_followups(as_of: str | None = None, horizon: int = 3) -> dict:
    today = parse_day(as_of) or date.today()
    upper = today + timedelta(days=max(0, horizon))
    rows = load_v2().get("followups", [])
    pending = [row for row in rows if followup_open(row) and "_parse_error" not in row]
    due, upcoming, undated = [], [], []
    for row in pending:
        snooze = parse_day(row.get("snooze_until"))
        if snooze and snooze > today: continue
        due_at = parse_day(followup_due_day(row))
        if due_at is None:
            undated.append(row); continue
        if due_at <= today:
            due.append(row)
        elif due_at <= upper:
            upcoming.append(row)
    def prompt(row: dict) -> dict:
        return {"id": row.get("id"), "question": row.get("prompt") or row.get("question"), "context": row.get("context", ""), "due_at": row.get("due_at"), "source_refs": row.get("source_refs", []), "last_checked_at": row.get("last_checked_at")}
    return {"as_of": today.isoformat(), "due": [prompt(row) for row in sorted(due, key=lambda row: (row.get("due_at") or "", row.get("id", "")))], "upcoming": [prompt(row) for row in sorted(upcoming, key=lambda row: (row.get("due_at") or "", row.get("id", "")))], "undated_pending": [prompt(row) for row in undated], "policy": "When due, first cite the original question, the context, and the agreement, then follow up naturally; never drop a bare 'how did it go' out of nowhere."}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default="")
    ap.add_argument("--horizon", type=int, default=3, help="upcoming window in days; default 3, 0 disables upcoming reminders")
    ap.add_argument("--format", choices={"json", "markdown"}, default="json")
    args = ap.parse_args()
    result = check_followups(args.as_of or None, args.horizon)
    if args.format == "markdown":
        print("# Follow-up check\n")
        print(f"Check date: {result['as_of']}\n")
        for group, title in (("due", "Due"), ("upcoming", "Upcoming"), ("undated_pending", "Missing date")):
            print(f"## {title}")
            for row in result[group]: print(f"- `{row['id']}`: {row['question']} ({row.get('due_at') or 'undated'})")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
