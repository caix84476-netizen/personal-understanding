#!/usr/bin/env python3
"""Single hard gate for a personal-understanding turn or session.

Model self-discipline is not enforcement. This script is: it runs the
closed-capture validation, the derivation ledger audit, and the followup
scheduler in one pass and exits non-zero when the turn may not proceed to
a "memory updated" claim. Run it after writes and before answering.

Exit codes: 0 = gates pass; 1 = structural failure or unclosed current-turn
captures; 2 = warnings present (usable, but must be reported).
"""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from backup_archive import BACKUP_DUE_DAYS, backup_age_days  # noqa: E402
from derivation_ledger import load_ledger  # noqa: E402


def run(name: str, *args: str) -> tuple[int, dict | str]:
    proc = subprocess.run([sys.executable, str(SCRIPTS / name), *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, proc.stdout.strip() + proc.stderr.strip()


def pending_detail(pending_ids: list[str]) -> list[dict]:
    """Age detail for pending captures: "current turn" cannot be expressed here, so keep leftover pending captures visible and actionable."""
    entries = load_ledger(ROOT)
    today = date.today()
    detail = []
    for capture_id in pending_ids:
        entry = entries.get(capture_id) or {}
        opened = str(entry.get("opened_at") or "")[:10]
        age_days = None
        if opened:
            try:
                age_days = (today - date.fromisoformat(opened)).days
            except ValueError:
                age_days = None
        detail.append({"capture_id": capture_id, "opened_at": opened or None, "age_days": age_days})
    return detail


def maintenance_reminders() -> dict:
    age = backup_age_days()
    return {
        "backup": {
            "age_days": age,
            "due": age is None or age >= BACKUP_DUE_DAYS,
            "instruction": "When the backup archive is overdue, run python scripts/backup_archive.py after the current task finishes (it re-authenticates the new archive and pushes it to the cloud); a backup is also required before migrations and after batches of important updates.",
        },
        "feedback": "If this turn's answer relied on personal memory and the user clearly corrected or confirmed something, or pointed out a miss, call personal_add_feedback (or scripts/record_feedback.py) per references/review-and-feedback-loops.md; do not record without verbatim evidence from the user.",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--allow-warnings", action="store_true", help="warnings are not treated as failure (by default warnings exit with code 2)")
    args = ap.parse_args()
    validate_code, validate = run("validate_memory.py", "--json", "--require-closed-captures")
    ledger = validate.get("derivation", {}) if isinstance(validate, dict) else {}
    followup_code, followups = run("followup_check.py")
    v2 = validate.get("v2", {}) if isinstance(validate, dict) else {}
    pending_ids = ledger.get("pending_capture_ids", [])
    gates = {
        "structure": {"pass": validate_code == 0, "status": validate.get("status") if isinstance(validate, dict) else "unknown", "errors": validate.get("errors", []) if isinstance(validate, dict) else []},
        "closed_captures": {"pass": not pending_ids, "pending": pending_ids, "detail": pending_detail(pending_ids)},
        "v2_archive": {"pass": v2.get("status") != "failed", "status": v2.get("status"), "errors": v2.get("errors", [])},
        "followups_due": {"count": len(followups.get("due", [])), "ids": [row.get("id") for row in followups.get("due", [])]},
    }
    hard_fail = not gates["structure"]["pass"] or not gates["closed_captures"]["pass"] or not gates["v2_archive"]["pass"]
    warnings_present = isinstance(validate, dict) and bool(validate.get("warnings"))
    print(json.dumps({"gate_version": "1.1.0", "hard_fail": hard_fail, "may_claim_memory_updated": not hard_fail, "gates": gates, "maintenance_reminders": maintenance_reminders()}, ensure_ascii=False, indent=2))
    if hard_fail:
        return 1
    if warnings_present and not args.allow_warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
