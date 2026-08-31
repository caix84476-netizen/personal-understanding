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
from turn_receipts import audit_turn  # noqa: E402


def run(name: str, *args: str) -> tuple[int, dict | str]:
    proc = subprocess.run([sys.executable, str(SCRIPTS / name), *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, proc.stdout.strip() + proc.stderr.strip()


def pending_detail(pending_ids: list[str]) -> list[dict]:
    """pending 捕获的龄期详情：无法表达"当前轮"，因此让残留 pending 可见、可处置。"""
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
            "instruction": "压缩包超期时，在当前任务完成后运行 python scripts/backup_archive.py（自动认证新压缩包并推送云端）；迁移前与重要更新批次后也必须备份。",
        },
        "feedback": "本轮回答若依赖个人记忆，且用户出现明确纠正/确认或指出落空，按 references/review-and-feedback-loops.md 调用 personal_add_feedback（或 scripts/record_feedback.py）；写不出用户原话证据就不记录。",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--allow-warnings", action="store_true", help="警告不视为失败（默认警告退出码为 2）")
    ap.add_argument("--turn-id", default="", help="校验当前 preflight receipt；个人 turn 未 capture/closed 时 fail closed")
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
    turn_gate = audit_turn(args.turn_id, ROOT) if args.turn_id else {"pass": True, "code": "not-requested"}
    gates["turn_receipt"] = turn_gate
    hard_fail = not gates["structure"]["pass"] or not gates["closed_captures"]["pass"] or not gates["v2_archive"]["pass"] or not turn_gate["pass"]
    warnings_present = isinstance(validate, dict) and bool(validate.get("warnings"))
    print(json.dumps({"gate_version": "2.0.0", "hard_fail": hard_fail, "may_claim_memory_updated": not hard_fail, "gates": gates, "maintenance_reminders": maintenance_reminders()}, ensure_ascii=False, indent=2))
    if hard_fail:
        return 1
    if warnings_present and not args.allow_warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
