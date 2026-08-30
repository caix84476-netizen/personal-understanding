#!/usr/bin/env python3
"""Prepare a model-led activation decision for personal context.

This entrypoint deliberately does not retrieve personal records. It returns the
current message, task-routing guidance, and the catalog entrypoint. The model
must decide whether personal context can change the answer before requesting
summary or deep retrieval.
"""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
from pathlib import Path
import sys

from followup_check import check_followups
from v2_archive import v2_audit

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from backup_archive import BACKUP_DUE_DAYS, backup_age_days  # noqa: E402

IMMEDIATE_REASONS = {"correction", "attribution", "privacy", "structure", "compression", "decision"}

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "memory" / "catalog.json"


def classify_signal(text: str) -> dict[str, object]:
    compact = " ".join(text.split())
    if not compact:
        return {"signal": "empty", "note": "No usable semantic signal in the current message; check the catalog first, without reading raw material."}
    if len("".join(compact.split())) <= 4:
        return {"signal": "low-information", "note": "Low-information messages must not get their topic from fixed emotion words; check the catalog first, then decide whether to read."}
    return {"signal": "normal", "note": "The model decides whether personal material could change the answer."}


def load_review_state() -> dict[str, object]:
    path = ROOT / "memory" / "review-state.json"
    if not path.exists():
        return {"important_updates_since_review": 0, "review_threshold": 8}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"important_updates_since_review": 0, "review_threshold": 8, "state_error": True}


def maintenance_status() -> dict[str, object]:
    """Turn maintenance facts such as backup age into per-turn machine output, independent of any single conversation's memory."""
    age = backup_age_days()
    return {
        "backup": {
            "age_days": age,
            "due": age is None or age >= BACKUP_DUE_DAYS,
            "note": "When overdue, run python scripts/backup_archive.py after the current task completes (it authenticates the archive and pushes it to the cloud).",
        }
    }


def review_alert(reason: str | None) -> dict[str, object]:
    state = load_review_state()
    updates = int(state.get("important_updates_since_review", 0))
    threshold = int(state.get("review_threshold", 8))
    due = updates >= threshold
    triggered = bool(reason or due)
    result: dict[str, object] = {
        "triggered": triggered,
        "reason": reason or ("threshold" if due else "not-due"),
        "due_by_count": due,
        "updates_since_review": updates,
        "threshold": threshold,
        "auto_mutation_authorized": triggered,
        "mutation": "review-cycle-required" if triggered else "none",
        "review_state": state,
    }
    if triggered:
        # preflight is the lightest per-turn step: run a lightweight v2 review
        # and emit scheduling instructions here; the full deep review
        # (review_skill --deep) is deferred until after the current task completes.
        from review_v2 import report as v2_report
        v2r = v2_report(deep=False)
        dict_warnings = [item for item in v2r.get("warnings", []) if isinstance(item, dict)]
        result["alerts"] = {
            "summary": v2r.get("summary", {}),
            "errors": v2r.get("errors", [])[:12],
            "warnings": dict_warnings[:12],
            "proposed_actions": [
                "After the current task completes, run python scripts/review_skill.py --deep --json to produce the full review package;",
                "Revise per references/review-and-feedback-loops.md: only derived records with clear source evidence may be changed; verbatim and sources are never rewritten.",
            ],
        }
        result["notice"] = "Review scheduling triggered: preflight stays lightweight and does not run the full deep review in this step; execute the proposed_actions above after the task completes."
    return result

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text")
    parser.add_argument("--budget", type=int, default=4000, help="only limits the routing response size, not later read budgets")
    parser.add_argument("--immediate-reason", choices=sorted(IMMEDIATE_REASONS), help="immediate-review trigger reasons kept from the original version")
    args = parser.parse_args()

    catalog_exists = CATALOG.exists()
    result = {
        "activation": {
            "mode": "model-decision",
            "default": "skip-if-personal-context-cannot-change-answer",
            "mixed_query_rule": "For technical content, pull in personal material only when a personal project, preference, privacy boundary, learning path, or decision constraint could change the answer.",
            "next_step": "When personal material could change the answer, first read the v2 survey (timeline spine, entity catalog, current state, follow-ups); then pick event/entity/context cards for probe, and run deep only on verbatim that needs verification.",
            "user_message_is_authoritative": True,
        },
        "preflight": {
            "mode": classify_signal(args.text)["signal"],
            "input": args.text,
            "effective_query": args.text,
            "note": classify_signal(args.text)["note"],
        },
        "catalog": {
            "available": catalog_exists,
            "path": "memory/catalog.json",
            "command": "python scripts/catalog_context.py --view routing --query <current-message>",
            "raw_sources_included": False,
            "v2_sources": "memory/v2 + sources/conversation",
        },
        "auto_review": review_alert(args.immediate_reason),
        "maintenance": maintenance_status(),
        "v2": {"version": "2.0.0", "followup_check": check_followups(), "archive_audit": v2_audit()},
        "retrieval_contract": {
            "survey": "A compact map scanning all current records and the history index without reading raw sources; nouns the user names explicitly are not the only relevance boundary",
            "irrelevant": "Exclude only when neither the global scan nor context expansion yields an explanatory connection",
            "possible": "Enter probe candidates; read only derived summaries, relation paths, and time labels",
            "medium": "Read direct records, relation neighbors, a few cross-domain anchors, and counterexamples; no raw sources",
            "high": "Read derived summaries, and on demand the raw sources behind supports/contradicts/supersedes, counter-evidence, and time neighbors",
            "seed_rule": "Model-selected IDs are seeds, not a relevance boundary; probe returns candidate_context and the model must judge keep/exclude/promote item by item",
            "related_ids": "Expand as weak/medium-relevance context candidates into probe; go deep only when forming an explanation or verification requires it",
            "cross_domain_frame": "Theme, emotional energy, behavior instances, behavior counterexamples, current stressors, resources/relationships, values and purposes, change over time, competing explanations, cross-corroboration",
            "current_conversation": "Takes precedence over archive summaries",
        },
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if len(encoded) > args.budget:
        for key in ("related_ids", "current_conversation", "cross_domain_frame", "mixed_query_rule", "seed_rule"):
            result["retrieval_contract"].pop(key, None)
            encoded = json.dumps(result, ensure_ascii=False, indent=2)
            if len(encoded) <= args.budget:
                break
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




