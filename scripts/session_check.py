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
from turn_receipts import audit_turn, receipt_dir  # noqa: E402
from view_freshness import views_stale  # noqa: E402


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
    ap.add_argument("--turn-id", default="", help="校验当前 preflight receipt；缺省时自动审计最近一次 receipt（不再静默跳过 turn 闸门）")
    ap.add_argument("--stale-days", type=int, default=7, help="历史遗留 pending/receipt 的降级龄期（天）：超过即从硬失败降级为可见警告")
    ap.add_argument("--light", action="store_true", help="轻量模式（2.8.0）：只查本轮 turn 闸门 + 未闭环 pending + 回访调度，跳过全库结构校验（validate_memory 子进程）。日常收尾推荐；全库校验留给维护轮/迁移验收。")
    args = ap.parse_args()
    rebuild_note = None
    if views_stale(ROOT):
        proc = subprocess.run([sys.executable, str(SCRIPTS / "rebuild_views.py")], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            rebuild_note = f"视图重建失败（闸门基于旧投影运行）：{(proc.stdout + proc.stderr).strip()[:400]}"
    # 2.8.0 --light: 跳过 validate_memory 全库校验子进程（本轮闸门不变，开销从秒级降到毫秒级）。
    # 结构/v2 门在 light 下标 "skipped-by-light"，不视为失败；pending 直接读台账，
    # 保持与完整模式同一来源。
    if args.light:
        from derivation_ledger import audit_ledger
        ledger_audit = audit_ledger(ROOT)
        validate_code, validate = 0, {"status": "skipped-by-light", "errors": [], "warnings": [], "derivation": {"pending_capture_ids": ledger_audit["pending_capture_ids"]}, "v2": {"status": "skipped-by-light", "errors": []}}
    else:
        validate_code, validate = run("validate_memory.py", "--json", "--require-closed-captures", "--stale-days", str(args.stale_days))
    ledger = validate.get("derivation", {}) if isinstance(validate, dict) else {}
    followup_code, followups = run("followup_check.py")
    v2 = validate.get("v2", {}) if isinstance(validate, dict) else {}
    pending_ids = ledger.get("pending_capture_ids", [])
    detail = pending_detail(pending_ids)
    # 历史遗留治理（2.7.0）：一次会话中断留下的 pending 曾把之后所有轮次的收尾
    # 全部毒化成 exit 1，而那些轮次对此无能为力。龄期达 --stale-days 的 pending
    # 降级为可见警告（可处置、可审计），近期 pending 依旧硬拦。
    recent = [row for row in detail if row["age_days"] is None or row["age_days"] < args.stale_days]
    stale = [row for row in detail if row["age_days"] is not None and row["age_days"] >= args.stale_days]
    recent_ids = [row["capture_id"] for row in recent]
    stale_note = f"{len(stale)} 条 pending 已超过 {args.stale_days} 天，按历史遗留降级为警告（不阻塞本轮收尾；处置见 personal_derivation_status）" if stale else None
    gates = {
        "structure": {"pass": validate_code == 0, "status": validate.get("status") if isinstance(validate, dict) else "unknown", "errors": validate.get("errors", []) if isinstance(validate, dict) else []},
        "closed_captures": {"pass": not recent_ids, "pending": pending_ids, "recent": recent_ids, "stale": stale, "stale_days": args.stale_days, "stale_note": stale_note, "detail": detail},
        "v2_archive": {"pass": v2.get("status") not in {"failed"}, "status": v2.get("status"), "errors": v2.get("errors", [])},
        "followups_due": {"count": len(followups.get("due", [])), "ids": [row.get("id") for row in followups.get("due", [])]},
    }
    # turn 闸门不再能靠"不传 turn_id"绕过：缺省时审计最近一次 receipt——
    # 交互会话里它就是当前轮；历史遗留的超龄未闭环 receipt 同样按龄期降级。
    if args.turn_id:
        turn_gate = audit_turn(args.turn_id, ROOT)
        turn_source = "explicit"
    else:
        receipt_files = sorted(receipt_dir(ROOT).glob("*.json"), key=lambda path: path.stat().st_mtime)
        latest = receipt_files[-1].stem if receipt_files else ""
        turn_gate = audit_turn(latest, ROOT) if latest else {"pass": True, "code": "not-requested"}
        turn_source = "latest-receipt-auto" if latest else "no-receipts"
    if not turn_gate.get("pass") and turn_gate.get("code") in {"required-turn-not-captured", "required-turn-not-closed"}:
        receipt = turn_gate.get("receipt") or {}
        created = str(receipt.get("created_at") or "")[:10]
        try:
            age = (date.today() - date.fromisoformat(created)).days
        except ValueError:
            age = None
        if age is not None and age >= args.stale_days:
            turn_gate = {**turn_gate, "pass": True, "code": f"{turn_gate['code']}-stale-downgraded", "age_days": age,
                         "note": f"该 receipt 已超 {args.stale_days} 天未闭环，按历史遗留降级为警告；处置请先 personal_derivation_status"}
    gates["turn_receipt"] = {**turn_gate, "turn_id_source": turn_source}
    hard_fail = not gates["structure"]["pass"] or not gates["closed_captures"]["pass"] or not gates["v2_archive"]["pass"] or not turn_gate["pass"]
    warnings_present = (isinstance(validate, dict) and bool(validate.get("warnings"))) or bool(stale) or bool(rebuild_note)
    output = {"gate_version": "2.2.0", "mode": "light" if args.light else "full", "hard_fail": hard_fail, "may_claim_memory_updated": not hard_fail, "gates": gates, "maintenance_reminders": maintenance_reminders()}
    if rebuild_note:
        output["view_rebuild_error"] = rebuild_note
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if hard_fail:
        return 1
    if warnings_present and not args.allow_warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
