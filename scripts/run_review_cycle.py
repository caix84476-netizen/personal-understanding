#!/usr/bin/env python3
"""Execute a bounded, verifiable deep-review maintenance cycle.

This runner only performs deterministic, source-safe maintenance itself. Semantic
record edits still require a source-grounded change plan from the reviewing model;
unknown inferences remain in inbox rather than being fabricated by automation.
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

from review_skill import make_report

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
STATE = ROOT / "memory" / "review-state.json"


def run_script(name: str, *args: str) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "script": name,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason", default="threshold")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--mark-reviewed", action="store_true", help="Only after a source-grounded semantic review has been completed.")
    parser.add_argument("--semantic-review-note", default="")
    args = parser.parse_args()

    report = make_report(True)
    # These are deterministic derived views and structural checks, never raw-source edits.
    rebuild = run_script("rebuild_views.py")
    validate = run_script("validate_memory.py", "--require-closed-captures")
    v2_review = run_script("review_v2.py", "--deep", "--json")
    infrastructure_ok = rebuild["returncode"] == 0 and validate["returncode"] == 0 and v2_review["returncode"] == 0
    if args.mark_reviewed and not args.semantic_review_note:
        parser.error("--mark-reviewed requires --semantic-review-note")
    completed = infrastructure_ok and args.mark_reviewed
    state = report["review_state"]
    if completed:
        state.update({
            "reviewed_on": date.today().isoformat(),
            "records": report["summary"]["records"],
            "important_updates_since_review": 0,
            "last_review_depth": "deep",
            "last_review_audit_version": report["review_version"],
            "last_review_summary": report["summary"],
            "last_review_reason": args.reason,
            "last_semantic_review_note": args.semantic_review_note,
            "last_review_outstanding_risks": {
                "priority_sources": len(report["audit"]["fidelity"]["priority_review_sources"]),
                "untraceable_records": len(report["audit"]["fidelity"]["untraceable_records"]),
                "summary_risks": len(report["audit"]["fidelity"]["summary_risks"]),
                "integration_gaps": len(report["audit"]["synthesis"]["integration_gaps"]),
            },
        })
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = {
        "cycle_version": "2.0.0",
        "reason": args.reason,
        "completed": completed,
        "infrastructure_ok": infrastructure_ok,
        "requires_semantic_review": infrastructure_ok and not completed,
        "automatic_changes": ["rebuild_views"] if rebuild["returncode"] == 0 else [],
        "semantic_changes": [],
        "semantic_change_boundary": "The reviewer never fabricates facts. Content that requires the model to verify against sources block by block stays as risks/candidates; an automation trigger must never write it directly into stable records.",
        "verification": [rebuild, validate, v2_review],
        "outstanding_risks": report["audit"],
        "v2_review": v2_review,
        "state_reset": completed,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Automatic deep review complete" if completed else "Automatic deep review finished infrastructure checks; awaiting source-grounded semantic review")
        print(f"Reason: {args.reason}")
        print(f"View rebuild: {'pass' if rebuild['returncode'] == 0 else 'fail'}; structure validation: {'pass' if validate['returncode'] == 0 else 'fail'}")
        print("No semantic inferences were written automatically; risks still requiring per-source verification are logged in review-state.json.")
    return 0 if infrastructure_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


