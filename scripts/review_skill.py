#!/usr/bin/env python3
"""Run a read-only health, fidelity, and integrated self-model review."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

from datetime import date
from pathlib import Path
import argparse
import json
import re
from collections import defaultdict
from typing import Any

from review_v2 import report as v2_review_report
from catalog_utils import ROOT, build_catalog, load_records, load_branches, split_ids, snippet
from review_context import synthesis_packet

TODAY = date.today()
RECORDS = ROOT / "memory" / "records"
BRANCHES = ROOT / "memory" / "branches"
REVIEW_STATE = ROOT / "memory" / "review-state.json"
CATALOG_JSON = ROOT / "memory" / "catalog.json"


def parse(path: Path) -> tuple[dict[str, str], str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: dict[str, str] = {}
    start = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                start = i + 1
                break
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[start:]).strip()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def load_state() -> dict[str, Any]:
    if not REVIEW_STATE.exists():
        return {"important_updates_since_review": 0, "review_threshold": 8}
    try:
        return json.loads(REVIEW_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"important_updates_since_review": 0, "review_threshold": 8, "state_error": True}


def implementation_gaps() -> list[str]:
    required_files = [
        ROOT / "references" / "self-distillation-policy.md",
        ROOT / "references" / "evaluation-policy.md",
        ROOT / "references" / "timeline-and-followup-policy.md",
        ROOT / "references" / "interaction-and-low-signal.md",
        ROOT / "references" / "retrieval-decision-trace.md",
        ROOT / "references" / "retrieval-policy.md",
        ROOT / "references" / "review-and-feedback-loops.md",
        ROOT / "references" / "maintenance-and-durability.md",
        ROOT / "references" / "conflict-and-correction-policy.md",
        ROOT / "scripts" / "query_context.py",
        ROOT / "scripts" / "preflight_context.py",
        ROOT / "scripts" / "catalog_context.py",
        ROOT / "scripts" / "retrieve_context.py",
        ROOT / "scripts" / "review_context.py",
        ROOT / "scripts" / "review_skill.py",
        ROOT / "scripts" / "register_important_update.py",
        ROOT / "memory" / "open-loops.md",
        ROOT / "memory" / "catalog.json",
    ]
    return [str(path.relative_to(ROOT)) for path in required_files if not path.exists()]


def fidelity_audit(catalog: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    record_by_id = {row["meta"].get("id"): row for row in rows}
    coverage = []
    for source in catalog["sources"]:
        path = ROOT / source["read_path"]
        size = int(source.get("byte_size", path.stat().st_size if path.exists() else 0))
        linked = source.get("record_refs", [])
        risk = []
        if not linked:
            risk.append("no derived records link to it")
        if size > 50000:
            risk.append("source is very long; needs chunked fidelity review")
        if source.get("warnings"):
            risk.append("has OCR/external-source boundaries")
        coverage.append({
            "path": source["path"],
            "source_type": source["source_type"],
            "bytes": size,
            "linked_records": linked,
            "risk": risk,
        })
    coverage.sort(key=lambda item: (-len(item["risk"]), -item["bytes"], item["path"]))

    untraceable_records = []
    conversation_only_records = []
    summary_risks = []
    for row in rows:
        meta = row["meta"]
        refs = split_ids(meta.get("source_refs"))
        record_id = meta.get("id")
        if refs and all(ref == "current-conversation" for ref in refs):
            conversation_only_records.append({
                "id": record_id,
                "kind": meta.get("kind"),
                "status": meta.get("status"),
                "reason": "source is the current-conversation tier and cannot be re-read independently like file sources; keep the boundary and do not misreport it as a format or relation error.",
            })
        if not refs:
            untraceable_records.append({
                "id": record_id,
                "kind": meta.get("kind"),
                "status": meta.get("status"),
                "reason": "no source_refs; cannot be traced back to any source.",
            })
        body_len = len(row["body"])
        if meta.get("kind") == "model" and not meta.get("supports"):
            summary_risks.append({"id": record_id, "risk": "model has no explicit supports evidence"})
        if meta.get("kind") == "model" and body_len > 450 and not any(term in row["body"] for term in ("反例", "不是", "可能", "条件", "竞争解释", "counterexample", "however", "alternative", "unless", "may not")):
            summary_risks.append({"id": record_id, "risk": "model summary is long but lacks obvious conditions, counterexamples, or uncertainty boundaries"})
        routing_kinds = {"state", "decision", "model", "value", "rule", "heuristic"}
        relation_fields = ("parent_ids", "related_ids", "supports", "contradicts", "supersedes")
        has_boundary = bool(meta.get("applies_when")) or any(split_ids(meta.get(field)) for field in relation_fields)
        if body_len < 90 and meta.get("kind") in routing_kinds and meta.get("status") == "current" and not has_boundary:
            summary_risks.append({"id": record_id, "risk": "high-level record is very short with no applies-when or relation boundary; it may keep only the task conclusion while losing the conditions or cost of forming it"})
        if meta.get("kind") == "event" and body_len > 900:
            structured = "**" in row["body"] or "来源边界" in row["body"] or "不能把" in row["body"] or "source boundary" in row["body"] or "must not" in row["body"]
            if not structured:
                summary_risks.append({"id": record_id, "risk": "event record is very long and may still be raw narrative without a routable summary"})

    source_intake = []
    for row in rows:
        meta = row["meta"]
        if meta.get("id", "").startswith("source.intake."):
            source_intake.append({
                "id": meta.get("id"),
                "summary_chars": len(row["body"]),
                "source_refs": split_ids(meta.get("source_refs")),
                "risk": "the summary is only source navigation and cannot replace item-by-item fidelity checks; current-conversation sources especially need traceable material added.",
            })

    source_ref_issues = []
    legacy_source_boundaries = []
    source_paths = {item["path"] for item in catalog["sources"]}
    record_ids = set(record_by_id)
    legacy_refs = {"sources/images"}
    for row in rows:
        meta = row["meta"]
        for ref in split_ids(meta.get("source_refs")):
            if ref in {"current-conversation", "memory/personality-model.md"} or ref in record_ids:
                continue
            if ref in legacy_refs:
                legacy_source_boundaries.append({"id": meta.get("id"), "source_ref": ref, "reason": "legacy source boundary is known but the original file was not kept with the archive; it must not be treated as currently re-readable evidence."})
                continue
            if not any(ref == path or ref.endswith("/" + path) or ref == Path(path).name for path in source_paths):
                source_ref_issues.append({"id": meta.get("id"), "source_ref": ref, "reason": "source path cannot be located in the sources directories"})

    catalog_drift = []
    if CATALOG_JSON.exists():
        try:
            stored = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
            stored_by_path = {item.get("path"): item for item in stored.get("sources", [])}
            for source in catalog["sources"]:
                old = stored_by_path.get(source["path"])
                if old and old.get("content_hash") and old.get("content_hash") != source.get("content_hash"):
                    catalog_drift.append(source["path"])
        except (OSError, json.JSONDecodeError):
            catalog_drift.append("memory/catalog.json is unparseable")

    return {
        "coverage": coverage,
        "untraceable_records": untraceable_records,
        "conversation_only_records": conversation_only_records,
        "summary_risks": summary_risks,
        "source_intake": source_intake,
        "source_ref_issues": source_ref_issues,
        "legacy_source_boundaries": legacy_source_boundaries,
        "catalog_drift": catalog_drift,
        "priority_review_sources": coverage[:15],
        "review_method": "Structural checks only find high-risk objects; use scripts/review_context.py --mode fidelity to compare sources and derived records block by block. An error-free format is not fidelity.",
    }


def synthesis_audit(catalog: dict[str, Any]) -> dict[str, Any]:
    packet = synthesis_packet(catalog, 100000)
    return {
        "model_inventory": [
            {"id": item["id"], "domain": item.get("domain"), "confidence": item.get("confidence"), "supports": item.get("supports", []), "related_ids": item.get("related_ids", [])}
            for item in packet["models"]
        ],
        "integration_gaps": packet["integration_gaps"],
        "cross_domain_axes": packet["cross_experience_questions"],
        "shared_source_groups": packet["shared_source_groups"],
        "current_decision_count": len(packet["current_decisions"]),
        "current_state_count": len(packet["current_states"]),
        "review_method": "A synthesis review cannot be file-by-file only; it must also compare recurring patterns, situational differences, counterexamples, and shifting directions across education, family, relationships, learning, work, and personal projects.",
    }


def retrieval_audit() -> dict[str, Any]:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    query = (ROOT / "scripts" / "query_context.py").read_text(encoding="utf-8")
    preflight = (ROOT / "scripts" / "preflight_context.py").read_text(encoding="utf-8")
    return {
        "model_activation_contract": all(term in skill for term in ("three layers of divergence", "survey is a compact routing map")) or all(term in skill for term in ("三层发散", "紧凑路由地图")),
        "global_survey_contract": "catalog_context.py --view" in skill and "probe" in skill,
        "preflight_does_not_retrieve": "subprocess" not in preflight and "query_context" not in preflight,
        "legacy_cues_default_off": "use_legacy_proactive = bool(args.legacy_proactive" in query and '"legacy-proactive-cues-active": false' not in skill.casefold(),
        "depth_interface": all((ROOT / "scripts" / name).exists() for name in ("catalog_context.py", "retrieve_context.py", "review_context.py")),
        "source_catalog_exists": (ROOT / "memory" / "catalog.json").exists(),
        "review_trace_documented": (ROOT / "references" / "retrieval-decision-trace.md").exists(),
    }


def make_report(deep: bool) -> dict[str, Any]:
    rows = load_records()
    catalog = build_catalog()
    branch_ids = {row["meta"].get("id") for row in load_branches() if row["meta"].get("id")}
    known_ids = {row["meta"].get("id") for row in rows if row["meta"].get("id")} | branch_ids
    current = [row for row in rows if row["meta"].get("status") == "current"]
    stale = []
    for row in current:
        meta = row["meta"]
        confirmed = parse_date(meta.get("last_confirmed") or meta.get("valid_from"))
        if confirmed and (TODAY - confirmed).days > 180:
            stale.append({"id": meta.get("id"), "age_days": (TODAY - confirmed).days})
    unresolved = []
    for row in rows:
        meta = row["meta"]
        for field in ("parent_ids", "related_ids", "supports", "contradicts", "supersedes"):
            for item in split_ids(meta.get(field)):
                if item not in known_ids:
                    unresolved.append(f"{meta.get('id')}:{field}:{item}")
    routing_kinds = {"state", "decision", "model", "value", "heuristic", "rule", "preference"}
    missing_domain = [row["meta"].get("id") for row in current if row["meta"].get("kind") in routing_kinds and not row["meta"].get("domain")]
    inbox = ROOT / "memory" / "inbox.md"
    inbox_count = sum(1 for line in inbox.read_text(encoding="utf-8").splitlines() if line.startswith("- ")) if inbox.exists() else 0
    open_loops = ROOT / "memory" / "open-loops.md"
    pending_loops = sum(1 for line in open_loops.read_text(encoding="utf-8").splitlines() if "status: pending" in line) if open_loops.exists() else 0
    state = load_state()
    updates = int(state.get("important_updates_since_review", 0))
    threshold = int(state.get("review_threshold", 8))
    gaps = implementation_gaps()
    audit = {
        "fidelity": fidelity_audit(catalog, rows),
        "synthesis": synthesis_audit(catalog),
        "retrieval": retrieval_audit(),
        "v2": v2_review_report(deep),
    }
    recommendations = [
        "First review priority_review_sources with review_context.py --mode fidelity, comparing sources and derived records block by block; the structural report cannot replace semantic verification.",
        "For high-level models, current states, and key decisions that only cite current-conversation, add concrete first-hand sources or explicitly mark them as current-conversation facts.",
        "Use review_context.py --mode synthesis for a cross-experience synthesis review: keep stable models, situational differences, counterexamples, changes, and evidence gaps; never promote a single experience directly into a personality conclusion.",
    ]
    return {
        "review_version": "2.0.0-compat",
        "deep": deep,
        "summary": {
            "records": len(rows),
            "current": len(current),
            "branches": len(branch_ids),
            "catalog_sources": catalog["counts"]["sources"],
            "important_updates_since_review": updates,
            "review_threshold": threshold,
            "review_due": updates >= threshold,
            "inbox_candidates": inbox_count,
            "pending_open_loops": pending_loops,
            "stale_current_records": len(stale),
            "missing_domains": len(missing_domain),
            "unresolved_links": len(unresolved),
            "implementation_gaps": len(gaps),
            "v2_status": audit["v2"]["status"],
            "v2_errors": audit["v2"]["summary"]["errors"],
            "v2_warnings": audit["v2"]["summary"]["warnings"],
            "review_state_record_drift": int(state.get("records", len(rows))) != len(rows),
        },
        "audit": audit if deep else {},
        "stale": stale,
        "missing_domain": missing_domain,
        "unresolved": unresolved,
        "implementation_gaps": gaps,
        "recommendations": recommendations if deep else [],
        "review_state": state,
        "approval": {
            "required_for_content_changes": False,
            "auto_mutation_authorized_on_trigger": True,
            "proposed_actions": recommendations if deep else [],
            "boundary": "Derived records with clear source grounding may be auto-revised; original sources are never rewritten, and uncertain inferences must not be promoted to facts.",
        },
        "mutation": "audit-only; the v2 structural review explicitly reports summary debt, missing verbatim captures, and semantic-verification gaps.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep", action="store_true", help="run source-fidelity, synthesis-model, and retrieval-contract audits")
    parser.add_argument("--json", action="store_true", help="output structured JSON")
    parser.add_argument("--mark-reviewed", action="store_true", help="only with --deep; explicitly register this deep audit as complete and reset the update counter")
    args = parser.parse_args()
    if args.mark_reviewed and not args.deep:
        parser.error("--mark-reviewed requires --deep")
    report = make_report(args.deep)
    if args.mark_reviewed:
        state = dict(report["review_state"])
        state.update({
            "reviewed_on": TODAY.isoformat(),
            "records": report["summary"]["records"],
            "important_updates_since_review": 0,
            "last_review_depth": "deep",
            "last_review_audit_version": report["review_version"],
            "last_review_summary": report["summary"],
        })
        REVIEW_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["review_state"] = state
        report["mutation"] = "review-state updated"
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    summary = report["summary"]
    print("Skill deep review (review phase is read-only; orchestration auto-revises on trigger)" if args.deep else "Skill review (read-only)")
    print(f"Records: {summary['records']}; current: {summary['current']}; branches: {summary['branches']}")
    print(f"Catalog sources: {summary['catalog_sources']}")
    print(f"Important updates since last review: {summary['important_updates_since_review']}; threshold: {summary['review_threshold']}; due: {summary['review_due']}")
    print(f"Inbox candidates: {summary['inbox_candidates']}")
    print(f"Pending open loops: {summary['pending_open_loops']}")
    print(f"Current records unconfirmed for over 180 days: {summary['stale_current_records']}")
    print(f"Current records missing a domain: {summary['missing_domains']}")
    print(f"Unresolved relation references: {summary['unresolved_links']}")
    print(f"Implementation gaps: {summary['implementation_gaps']}")
    print(f"Last review: {report['review_state'].get('reviewed_on', 'none')}; last depth: {report['review_state'].get('last_review_depth', 'unknown')}")
    if args.deep:
        fidelity = report["audit"]["fidelity"]
        synthesis = report["audit"]["synthesis"]
        retrieval = report["audit"]["retrieval"]
        print("Deep checks:")
        print(f"- Source fidelity: {len(fidelity['coverage'])} sources have a coverage row; {len(fidelity['untraceable_records'])} records cannot be traced to a concrete source")
        print(f"- Summary risks: {len(fidelity['summary_risks'])} records need comparison of source, summary, counterexamples, and uncertainty")
        print(f"- Source-chain issues: {len(fidelity['source_ref_issues'])}; catalog drift: {len(fidelity['catalog_drift'])} sources; review-state record count drift: {summary['review_state_record_drift']}")
        print(f"- Synthesis: {len(synthesis['model_inventory'])} models; {len(synthesis['integration_gaps'])} synthesis connections/evidence gaps")
        print(f"- Retrieval tiers: model activation={retrieval['model_activation_contract']}; preflight does not retrieve={retrieval['preflight_does_not_retrieve']}; depth interface={retrieval['depth_interface']}")
        print("- Review packets: use scripts/review_context.py --mode fidelity or --mode synthesis")
        if fidelity["priority_review_sources"]:
            print(f"- Priority sources: {[item['path'] for item in fidelity['priority_review_sources'][:8]]}")
        if report["recommendations"]:
            for recommendation in report["recommendations"]:
                print(f"- Recommendation: {recommendation}")
    else:
        if report["stale"]:
            print(f"- Recommendation: stale-check {report['stale'][:5]}")
        if report["missing_domain"]:
            print(f"- Recommendation: add domains only where they have real routing value ({report['missing_domain'][:5]})")
        if report["unresolved"]:
            print(f"- Recommendation: check unresolved links ({report['unresolved'][:5]})")
    print("Changes: this deep review registered" if args.mark_reviewed else "Changes: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





