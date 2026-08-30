#!/usr/bin/env python3
"""Deep v2 review: provenance, timeline, entity graph, follow-ups, and hypothesis readiness."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()
import argparse, json
from collections import Counter
from v2_archive import followup_is_due, load_v2, v2_audit
from catalog_utils import ROOT, load_records, split_ids
from derivation_ledger import audit_ledger
from record_feedback import read_feedback, miss_summary


def report(deep: bool = False) -> dict:
    data = load_v2(); audit = v2_audit(strict=False)
    events = data.get("events", []); entities = data.get("entities", []); contexts = data.get("contexts", []); fragments = data.get("fragments", []); followups = data.get("followups", []); hypotheses = data.get("hypotheses", [])
    issues = []; warnings = list(audit.get("warnings", [])); errors = list(audit.get("errors", []))
    derivation = audit_ledger(ROOT)
    warnings.extend(derivation.get("warnings", [])); errors.extend(derivation.get("errors", []))
    undated = [row for row in events if not row.get("date_start")]
    if undated: warnings.append({"code": "timeline-undated", "count": len(undated), "sample": [row.get("record_id") for row in undated[:12]]})
    orphan_entities = [row for row in entities if not row.get("record_refs") and not row.get("event_refs") and not row.get("fragment_refs")]
    if orphan_entities: warnings.append({"code": "entity-without-story", "count": len(orphan_entities), "sample": [row.get("id") for row in orphan_entities[:12]]})
    no_context_entities = [row for row in entities if not row.get("context_refs") and row.get("mention_count", 0) > 0]
    if no_context_entities: warnings.append({"code": "entity-without-context-card", "count": len(no_context_entities), "sample": [row.get("id") for row in no_context_entities[:12]]})
    summary_only = [row for row in fragments if row.get("fidelity") == "summary_only"]
    if summary_only: warnings.append({"code": "summary-only-debt", "count": len(summary_only), "note": "Old summaries may be used for migration and routing, but must never impersonate verbatim captures."})
    unresolved = [row for row in data.get("relations", []) if not row.get("resolved", True)]
    if unresolved: warnings.append({"code": "relation-unresolved", "count": len(unresolved), "sample": [row.get("id") for row in unresolved[:12]]})
    due = [row for row in followups if followup_is_due(row)]
    if due: warnings.append({"code": "followups-due", "count": len(due), "ids": [row.get("id") for row in due]})
    if not hypotheses: warnings.append({"code": "hypothesis-layer-empty", "note": "Having no candidate causal hypotheses is not an error; generate them only when an explanation is needed."})
    feedback = read_feedback(ROOT / "memory" / "v2" / "feedback.jsonl")
    if feedback:
        feedback_summary = miss_summary(feedback)
        if feedback_summary["missed_or_corrected"]:
            warnings.append({"code": "feedback-miss-streak", "missed_or_corrected": feedback_summary["missed_or_corrected"], "worst_memory_ids": feedback_summary["worst_memory_ids"], "note": "These memories were repeatedly used in answers and then corrected or flagged as misses; verify them first during deep review."})
    # Compare the old archive to the v2 generated views.
    old_records = load_records(); legacy_current = sum(row["meta"].get("status") == "current" for row in old_records)
    high_weight = [row for row in events if int(row.get("salience", 0)) >= 2]
    sections = {
        "provenance": {"verbatim_fragments": sum(row.get("fidelity") == "verbatim" for row in fragments), "exact_attachment_fragments": sum(row.get("fidelity") == "exact_attachment" for row in fragments), "summary_only_fragments": len(summary_only), "legacy_current_records": legacy_current, "derivation_closure": derivation.get("counts", {})},
        "timeline": {"entries": len(events), "undated_entries": len(undated), "high_weight_entries": len(high_weight), "salience_distribution": dict(Counter(row.get("salience_label") for row in events))},
        "entities": {"entities": len(entities), "context_cards": len(contexts), "entities_with_story": sum(bool(row.get("event_refs") or row.get("fragment_refs")) for row in entities), "pair_facets": sum(row.get("kind") == "facet" for row in contexts)},
        "followups": {"pending": sum(row.get("status", "pending") == "pending" for row in followups), "due": len(due)},
        "hypotheses": {"candidate_count": len(hypotheses), "with_supports": sum(bool(row.get("supports")) for row in hypotheses)},
        "feedback": miss_summary(feedback) if feedback else {"total_feedback": 0, "helpful": 0, "missed_or_corrected": 0, "worst_memory_ids": []},
    }
    status = "failed" if errors else ("warnings" if warnings else "clean")
    result = {"review_version": "2.0.0", "mode": "deep" if deep else "structural", "status": status, "summary": {"errors": len(errors), "warnings": len(warnings)}, "sections": sections, "errors": errors, "warnings": warnings, "recommendation": "A structural pass is not a semantic pass: fix critical errors first, then verify summary-only fragments, date gaps, attribution to people, and causal hypotheses one by one."}
    if deep:
        result["semantic_review_contract"] = {"must_compare": ["verbatim vs events", "verbatim vs entity profiles", "events vs chronological order", "shared contexts between people", "facts/feelings/interpretations/hypotheses", "contradictions and counterexamples"], "cannot_claim": ["an old summary is a verbatim capture", "co-occurrence is causation", "absence from the archive means it does not exist", "a structurally clean archive means correct understanding"]}
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-warning", action="store_true")
    args = ap.parse_args()
    result = report(args.deep)
    if args.json: print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"v2 review: {result['status']}; errors {result['summary']['errors']}; warnings {result['summary']['warnings']}")
        for item in result["errors"]: print(f"[FAIL] {item}")
        for item in result["warnings"][:30]: print(f"[WARN] {item}")
        print(result["recommendation"])
    if result["summary"]["errors"]: return 1
    if args.fail_on_warning and result["summary"]["warnings"]: return 2
    return 0


if __name__ == "__main__": raise SystemExit(main())
