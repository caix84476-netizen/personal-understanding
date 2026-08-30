#!/usr/bin/env python3
"""Build model-facing packets for fidelity and integrated self-model review."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
from pathlib import Path
from typing import Any

from catalog_utils import ROOT, build_catalog, linked_records, load_records, parse_frontmatter, snippet, split_ids
from source_audit import audit_records


def source_item(catalog: dict[str, Any], requested: str) -> dict[str, Any] | None:
    normalized = requested.replace("\\", "/").casefold()
    for item in catalog["sources"]:
        if item["path"].casefold() == normalized or item["read_path"].casefold() == normalized or Path(item["path"]).name.casefold() == normalized:
            return item
    return None


def source_body(source: dict[str, Any], offset: int, limit: int) -> tuple[str, bool, int | None]:
    path = ROOT / source["read_path"]
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        ocr_path = source.get("ocr_path")
        if ocr_path and (ROOT / ocr_path).exists():
            content = (ROOT / ocr_path).read_text(encoding="utf-8", errors="replace")
        else:
            content = "[Original image source; this review packet does not embed image pixels, read back via read_path.]"
    else:
        content = path.read_text(encoding="utf-8", errors="replace")
    end = min(len(content), offset + limit)
    chunk = content[offset:end]
    return chunk, end < len(content), end if end < len(content) else None


def record_rows() -> list[dict[str, Any]]:
    return load_records()


def compact_record(row: dict[str, Any]) -> dict[str, Any]:
    meta = row["meta"]
    return {
        "id": meta.get("id"),
        "kind": meta.get("kind"),
        "status": meta.get("status"),
        "confidence": meta.get("confidence"),
        "sensitivity": meta.get("sensitivity"),
        "domain": meta.get("domain"),
        "valid_from": meta.get("valid_from"),
        "last_confirmed": meta.get("last_confirmed"),
        "source_refs": split_ids(meta.get("source_refs")),
        "supports": split_ids(meta.get("supports")),
        "related_ids": split_ids(meta.get("related_ids")),
        "summary": snippet(row["body"], 900),
    }


def fidelity_packet(catalog: dict[str, Any], requested: str, offset: int, source_chars: int) -> dict[str, Any]:
    source = source_item(catalog, requested)
    if not source:
        raise SystemExit(f"Source not found: {requested}")
    content, truncated, next_offset = source_body(source, offset, source_chars)
    rows = record_rows()
    linked = [compact_record(row) for row in linked_records(source["path"], rows)]
    return {
        "review_version": "2.0.0-compat",
        "mode": "fidelity",
        "source": {
            "id": source["id"],
            "path": source["path"],
            "source_type": source["source_type"],
            "summary": source["summary"],
            "warnings": source["warnings"],
            "offset": offset,
            "content": content,
            "truncated": truncated,
            "next_offset": next_offset,
        },
        "derived_records": linked,
        "review_contract": {
            "preserve": "First verify the original user wording, people/speakers, dates, numbers, causal strength, and uncertainty, then judge whether the summary kept what actually shaped the user's understanding.",
            "omission": "List facts, experiences, values, counterexamples, changes, and open questions that matter in the source but are entirely missing from the derived records.",
            "distortion": "List where the summary turned someone else's statement into user fact, possibility into certainty, a one-off scene into stable personality, or a later state over history.",
            "overcompression": "Judge whether only task conclusions remain, losing formative experiences, situational conditions, costs, counterexamples, and cross-experience links.",
            "source_boundary": "Third-party analysis, OCR, and external chats must stay separate from user verbatim; user corrections outrank older summaries.",
            "action": "Propose only evidence-backed record updates: additions, splits, downgrades, supersedes, added supports, or inbox entries; never auto-overwrite the raw source.",
        },
    }


def synthesis_packet(catalog: dict[str, Any], budget: int) -> dict[str, Any]:
    records = record_rows()
    current = [row for row in records if row["meta"].get("status") == "current"]
    models = [compact_record(row) for row in current if row["meta"].get("kind") == "model"]
    decisions = [compact_record(row) for row in current if row["meta"].get("kind") == "decision"]
    states = [compact_record(row) for row in current if row["meta"].get("kind") == "state"]
    values = [compact_record(row) for row in current if row["meta"].get("kind") in {"value", "rule", "heuristic", "preference"}]
    model_ids = {item["id"] for item in models}
    integration_gaps = []
    for item in models:
        if not item.get("supports"):
            integration_gaps.append({"id": item["id"], "gap": "No explicit supporting evidence"})
        if not any(item.get(field) for field in ("related_ids", "parent_ids", "supports", "contradicts", "supersedes")):
            integration_gaps.append({"id": item["id"], "gap": "No cross-record relations; may not yet be integrated into synthesis"})
        if len(item.get("summary", "")) > 500 and not any(term in item.get("summary", "") for term in ("反例", "不是", "条件", "可能", "但")):
            integration_gaps.append({"id": item["id"], "gap": "Summary is long but lacks visible condition/counterexample boundaries"})
    shared_source_groups: dict[str, list[str]] = {}
    for item in models:
        for ref in item.get("source_refs", []):
            shared_source_groups.setdefault(ref, []).append(item["id"])
    duplicate_axes = [
        {"source_ref": ref, "models": ids}
        for ref, ids in shared_source_groups.items()
        if len(ids) >= 3
    ]
    packet = {
        "review_version": "2.0.0-compat",
        "mode": "synthesis",
        "models": models,
        "current_decisions": decisions,
        "current_states": states,
        "values_rules_preferences": values,
        "integration_gaps": integration_gaps,
        "shared_source_groups": duplicate_axes,
        "cross_experience_questions": [
            "Which judgments recur across education/career, family/home, relationships, learning, work, health, and personal projects strongly enough to become cross-scene models?",
            "Which models rest on a single experience and must not be stated as stable traits?",
            "In which scenes does the same model hold, and where do counterexamples exist or pressure, relationships, and stakes change it?",
            "Do current decisions genuinely connect to values and costs formed in the past, or do they remain isolated task records?",
            "Which records only describe what the user did without saying how the experience changed the user's judgment, boundaries, or future choices?",
            "Which models actually duplicate, over-slice, or conflict with one another and should be merged, split, or kept as competing explanations?",
        ],
        "review_contract": {
            "goal": "Synthesize value ordering, formation conditions, situational differences, costs, counterexamples, and the direction of ongoing change.",
            "counterevidence_required": "For every stable model, list at least: where it applies, supporting sources, counterexamples/competing explanations, time range, and what new evidence would change it.",
            "do_not_do": "Do not assume understanding from record count; do not upgrade one high-emotion event into a stable personality trait; do not substitute model summaries for first-hand source verification.",
            "output": "Output must separate stable models, recent changes, undecided explanations, evidence gaps, and high-risk items that need a read-back of the source.",
        },
    }
    encoded = json.dumps(packet, ensure_ascii=False)
    if len(encoded) > budget:
        packet["values_rules_preferences"] = packet["values_rules_preferences"][:20]
        packet["current_states"] = packet["current_states"][:30]
        packet["current_decisions"] = packet["current_decisions"][:20]
        packet["note"] = "Budget too small: models, decisions, states, and the review contract are prioritized."
    return packet


def coverage_packet(catalog: dict[str, Any]) -> dict[str, Any]:
    records = record_rows()
    record_by_id = {row["meta"].get("id"): row for row in records}
    risks = []
    for source in catalog["sources"]:
        linked = source.get("record_refs", [])
        path = ROOT / source["read_path"]
        size = path.stat().st_size if path.exists() else 0
        risk = (3 if not linked else 0) + (2 if size > 50000 else 1 if size > 10000 else 0) + (1 if source.get("warnings") else 0)
        risks.append({"path": source["path"], "source_type": source["source_type"], "bytes": size, "linked_records": linked, "risk": risk, "reason": "No derived records / long source / OCR or external-source boundary present"})
    risks.sort(key=lambda item: (-item["risk"], -item["bytes"], item["path"]))
    unresolved_source_refs = audit_records()
    untraceable = []
    conversation_only = []
    for row in records:
        meta = row["meta"]
        refs = split_ids(meta.get("source_refs"))
        if refs and all(ref == "current-conversation" for ref in refs):
            conversation_only.append({"id": meta.get("id"), "kind": meta.get("kind"), "reason": "Source lives at the conversation tier and cannot be read back independently like a file source; the boundary is kept, not misreported as a structural error"})
        if not refs:
            untraceable.append({"id": meta.get("id"), "kind": meta.get("kind"), "reason": "No source_refs"})
    return {
        "review_version": "2.0.0-compat",
        "mode": "coverage",
        "sources_by_risk": risks,
        "untraceable_records": untraceable,
        "unresolved_source_refs": unresolved_source_refs,
        "conversation_only_records": conversation_only,
        "review_contract": {
            "priority": "Review first: long sources, sources without derived records, OCR/external sources, and top-level models plus recently changed records from conversation-tier sources. Conversation-tier sources are an acceptable source boundary but must not pose as independently readable files.",
            "do_not_infer": "A missing link does not mean worthless; it only means unverifiable right now and should enter the manual/model read-back queue.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fidelity", "synthesis", "coverage"), required=True)
    parser.add_argument("--source")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--source-chars", type=int, default=16000)
    parser.add_argument("--budget", type=int, default=50000)
    args = parser.parse_args()
    catalog = build_catalog()
    if args.mode == "fidelity":
        if not args.source:
            parser.error("--mode fidelity requires --source")
        result = fidelity_packet(catalog, args.source, args.offset, args.source_chars)
    elif args.mode == "synthesis":
        result = synthesis_packet(catalog, args.budget)
    else:
        result = coverage_packet(catalog)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


