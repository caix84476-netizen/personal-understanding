#!/usr/bin/env python3
"""Load personal context with bounded, model-led contextual expansion.

The model still decides what is relevant. Record IDs are seeds, not a hard
context boundary: probe exposes a compact neighborhood for cross-domain
checking; deep loads evidence, conflict, replacement, and temporal neighbors.
"""
from __future__ import annotations

from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any

from catalog_utils import ROOT, build_catalog, load_records, parse_frontmatter, query_terms, split_ids, snippet

RELATION_FIELDS = ("supports", "contradicts", "supersedes", "parent_ids", "related_ids")
EVIDENCE_FIELDS = ("supports", "contradicts", "supersedes")
HIGH_CONTEXT_KINDS = {"model", "value", "heuristic", "decision", "state", "event", "rule", "preference"}


def record_map() -> dict[str, dict[str, Any]]:
    return {row["meta"].get("id"): row for row in load_records() if row["meta"].get("id")}


def source_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["path"]: item for item in catalog["sources"]}


def source_content(source: dict[str, Any], limit: int) -> str:
    path = ROOT / source["read_path"]
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        ocr_path = source.get("ocr_path")
        if ocr_path and (ROOT / ocr_path).exists():
            text = (ROOT / ocr_path).read_text(encoding="utf-8", errors="replace")
            return "[OCR of the image; verify against the original]\n" + snippet(text, limit)
        return "[Original image source; this tool does not embed image pixels, read the original back via read_path.]"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[Cannot read raw source: {exc}]"
    _, body = parse_frontmatter(path)
    return snippet(body or text, limit)


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
        "valid_until": meta.get("valid_until"),
        "last_confirmed": meta.get("last_confirmed"),
        "aliases": split_ids(meta.get("aliases")),
        "applies_when": meta.get("applies_when", ""),
        "parent_ids": split_ids(meta.get("parent_ids")),
        "source_refs": split_ids(meta.get("source_refs")),
        "supports": split_ids(meta.get("supports")),
        "related_ids": split_ids(meta.get("related_ids")),
        "contradicts": split_ids(meta.get("contradicts")),
        "supersedes": split_ids(meta.get("supersedes")),
        "summary": snippet(row["body"], 900),
    }


def searchable(row: dict[str, Any]) -> str:
    meta = row["meta"]
    return " ".join(
        [meta.get(key, "") for key in ("id", "domain", "kind", "applies_when", "aliases")] + [row["body"]]
    ).casefold()


def semantic_score(row: dict[str, Any], terms: list[str]) -> int:
    if not terms:
        return 0
    haystack = searchable(row)
    return sum(1 for term in terms if term in haystack)


def inverse_links(records: dict[str, dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """Add reverse evidence/navigation edges; archives are not a context boundary."""
    incoming: dict[str, list[tuple[str, str]]] = {}
    for source_id, row in records.items():
        meta = row["meta"]
        for field in RELATION_FIELDS:
            for target in split_ids(meta.get(field)):
                if target in records:
                    incoming.setdefault(target, []).append((source_id, f"inverse_{field}"))
    return incoming


def expand_context(
    seed_ids: list[str],
    records: dict[str, dict[str, Any]],
    query: str,
    max_candidates: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (high_evidence_rows, compact candidate pool, stopped candidates)."""
    terms = query_terms(query)
    incoming = inverse_links(records)
    seed_set = set(seed_ids)
    seen: dict[str, dict[str, Any]] = {}
    queue = deque((seed_id, 0) for seed_id in seed_ids)
    paths: dict[str, list[str]] = {seed_id: [seed_id] for seed_id in seed_ids}

    while queue:
        current, depth = queue.popleft()
        if depth >= 2:
            continue
        row = records.get(current)
        if not row:
            continue
        meta = row["meta"]
        edges: list[tuple[str, str]] = []
        for field in RELATION_FIELDS:
            edges.extend((target, field) for target in split_ids(meta.get(field)))
        edges.extend(incoming.get(current, []))
        for target, relation in edges:
            if target not in records or target in seed_set:
                continue
            candidate_path = paths.get(current, [current]) + [target]
            paths.setdefault(target, candidate_path)
            priority = 0
            base_relation = relation[len("inverse_") :] if relation.startswith("inverse_") else relation
            if base_relation in EVIDENCE_FIELDS:
                priority = 4
            elif base_relation == "parent_ids":
                priority = 2
            else:
                priority = 1
            row_score = semantic_score(records[target], terms)
            current_bonus = 2 if records[target]["meta"].get("status") == "current" else 0
            candidate = seen.setdefault(
                target,
                {"id": target, "row": records[target], "relations": [], "path": candidate_path, "priority": 0, "semantic_score": row_score},
            )
            candidate["relations"].append(relation)
            candidate["priority"] = max(candidate["priority"], priority + current_bonus + min(row_score, 3))
            if depth + 1 < 2:
                queue.append((target, depth + 1))

    # Add a small cross-domain safety net. This is deliberately not a hidden
    # relevance verdict: it is a compact pool the model can reject or promote.
    by_domain: dict[str, list[tuple[int, str, dict[str, Any]]]] = {}
    for record_id, row in records.items():
        if record_id in seed_set or row["meta"].get("status") != "current":
            continue
        score = semantic_score(row, terms)
        if score or row["meta"].get("kind") in {"model", "value", "heuristic"}:
            domain = row["meta"].get("domain") or "domain.unclassified"
            by_domain.setdefault(domain, []).append((score, record_id, row))
    for _, items in by_domain.items():
        for score, record_id, row in sorted(items, key=lambda item: (item[0], item[1]), reverse=True)[:3]:
            candidate = seen.setdefault(record_id, {"id": record_id, "row": row, "relations": [], "path": [record_id], "priority": 0, "semantic_score": score})
            candidate["priority"] = max(candidate["priority"], score + 1)
            candidate["relations"].append("cross_domain_anchor")

    ranked = sorted(seen.values(), key=lambda item: (item["priority"], item["semantic_score"], item["id"]), reverse=True)
    chosen = ranked[:max_candidates]
    stopped = ranked[max_candidates:]
    high_evidence = [item for item in chosen if any((relation[len("inverse_") :] if relation.startswith("inverse_") else relation) in EVIDENCE_FIELDS for relation in item["relations"])]

    candidates: list[dict[str, Any]] = []
    for item in chosen:
        row = item["row"]
        meta = row["meta"]
        evidence = any((relation[len("inverse_") :] if relation.startswith("inverse_") else relation) in EVIDENCE_FIELDS for relation in item["relations"])
        candidates.append(
            {
                **compact_record(row),
                "candidate_tier": "evidence-or-conflict" if evidence else ("weak-context" if item["priority"] <= 2 else "possible-context"),
                "why_candidate": "; ".join(dict.fromkeys(item["relations"])),
                "relation_path": item["path"],
                "model_must_decide": True,
                "decision": "pending",
                "promotion_options": ["exclude", "keep-as-background", "promote-to-deep"],
                "raw_body_included": False,
            }
        )
    stopped_items = [
        {"id": item["id"], "reason": "Stopped at the candidate pool limit; increase --max-context-candidates if needed.", "relation_path": item["path"]}
        for item in stopped[:20]
    ]
    return [item["row"] for item in high_evidence], candidates, stopped_items


def match_source_ref(ref: str, source: dict[str, Any]) -> bool:
    path = source["path"]
    return ref == path or ref == Path(path).name or ref == Path(path).stem or ref.endswith("/" + Path(path).name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", default="", help="Model-selected seed record IDs; seeds are not a hard context boundary.")
    parser.add_argument("--level", choices=("probe", "summary", "deep"), default="summary")
    parser.add_argument("--evidence-ids", default="", help="Explicit conflict/history evidence IDs selected after survey/probe.")
    parser.add_argument("--query", default="", help="Current message; used only to surface possible cross-domain candidates.")
    parser.add_argument("--max-context-candidates", type=int, default=40)
    parser.add_argument("--budget", type=int, default=12000)
    parser.add_argument("--source-chars", type=int, default=2400)
    parser.add_argument("--trace-reason", default="")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()

    catalog = build_catalog()
    records = record_map()
    sources = source_map(catalog)
    requested_ids = split_ids(args.ids)
    explicit_evidence_ids = split_ids(args.evidence_ids)
    seed_ids = [item for item in requested_ids if item in records]
    missing_ids = [item for item in requested_ids + explicit_evidence_ids if item not in records]
    query_terms_value = query_terms(args.query)
    query_suggestions = []
    if not seed_ids and args.query:
        # Query-only is a routing aid, not an implicit retrieval decision. The
        # model must inspect survey and explicitly pass seed IDs on the next call.
        ranked = sorted(
            (row for row in records.values() if row["meta"].get("status") == "current"),
            key=lambda row: (semantic_score(row, query_terms_value), row["meta"].get("kind") in HIGH_CONTEXT_KINDS),
            reverse=True,
        )
        query_suggestions = [compact_record(row) for row in ranked if semantic_score(row, query_terms_value) > 0][:20]

    evidence_rows, context_candidates, stopped = expand_context(seed_ids, records, args.query, max(1, args.max_context_candidates))
    evidence_ids = [row["meta"].get("id") for row in evidence_rows]
    for evidence_id in explicit_evidence_ids:
        if evidence_id in records and evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)

    selected_rows = [records[item] for item in seed_ids]
    loaded_rows = list(selected_rows)
    if args.level == "deep":
        loaded_ids = {row["meta"].get("id") for row in loaded_rows}
        for record_id in evidence_ids:
            if record_id in records and record_id not in loaded_ids:
                loaded_rows.append(records[record_id])
                loaded_ids.add(record_id)

    source_paths: list[str] = []
    if args.level == "deep":
        for row in loaded_rows:
            for ref in split_ids(row["meta"].get("source_refs")):
                for source in catalog["sources"]:
                    if match_source_ref(ref, source) and source["path"] not in source_paths:
                        source_paths.append(source["path"])

    source_items = []
    for path in source_paths:
        source = sources.get(path)
        if source:
            item = dict(source)
            item["content"] = source_content(source, args.source_chars)
            source_items.append(item)

    selected_set = set(seed_ids)
    loaded_set = {row["meta"].get("id") for row in loaded_rows}
    excluded = [
        {"id": item["id"], "reason": "Historical material not entered in the current deep read; load only for time verification, conflict investigation, or explicit model promotion."}
        for item in catalog["records"]
        if item["id"] not in selected_set and item.get("status") in {"archived", "superseded"}
    ][:12]

    trace = {
        "activation": "retrieve",
        "reason": args.trace_reason or ("No seeds passed in; this only returns routing candidates, and keyword hits must not implicitly count as read." if not seed_ids else "The model selected seeds from the global survey; the retriever automatically adds limited cross-domain context and does not treat seeds as a relevance boundary."),
        "candidates": [
            {"id": item, "relevance_level": "high" if args.level == "deep" else "medium", "why_relevant": "Seed records selected by the model from the global survey.", "why_not_deeper": "" if args.level == "deep" else "Raw sources not read yet."}
            for item in seed_ids
        ],
        "read": {"records": seed_ids, "support_records": [record_id for record_id in loaded_set if record_id not in selected_set], "sources": source_paths},
        "scan": {
            "phase": "deep" if args.level == "deep" else "probe",
            "surveyed_current": catalog.get("survey", {}).get("counts", {}).get("current", 0),
            "history_indexed": catalog.get("survey", {}).get("counts", {}).get("history", 0),
            "selected_for_probe_or_deep": seed_ids,
            "explicit_evidence_ids": explicit_evidence_ids,
            "candidate_transitions": [{"id": item, "from": "survey", "to": "deep" if args.level == "deep" else "probe"} for item in seed_ids],
            "context_expansion": {"candidate_count": len(context_candidates), "loaded_evidence_count": len(evidence_ids) if args.level == "deep" else 0, "policy": "seed IDs are starting points; inspect possible/weak candidates before declaring them irrelevant."},
            "stopped_candidates": stopped,
            "stop_rule": "Inspect summaries and relation paths first; go deep only when a hypothesis needs evidence, or a time conflict, counterexample, or unclear source attribution exists. Wider reading cannot replace evidence, and cross-domain co-occurrence only forms a candidate explanation.",
        },
        "excluded": excluded,
        "uncertainty": {"missing_ids": missing_ids, "hypotheses": [], "evidence_gaps": [], "note": "Stop expanding and state the gap when material is insufficient for a conclusion; do not pass candidate summaries off as fact." if args.level == "deep" and not source_items else ""},
    }

    result = {
        "retrieval_version": "2.0.0-compat",
        "read": {"level": args.level, "records": seed_ids, "sources": source_paths},
        "records": [compact_record(row) for row in loaded_rows],
        "context_candidates": context_candidates if args.level != "deep" else [item for item in context_candidates if item["id"] not in loaded_set],
        "query_suggestions": query_suggestions,
        "sources": source_items,
        "trace": trace,
        "omitted": {"missing_ids": missing_ids},
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if len(encoded) > args.budget:
        result["context_candidates"] = [{key: value for key, value in item.items() if key not in {"summary", "relation_path"}} | {"summary": snippet(item.get("summary", ""), 420)} for item in result["context_candidates"][: max(8, args.max_context_candidates // 2)]]
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if len(encoded) > args.budget:
        result["note"] = "Budget too small: seeds, context candidates, and read paths are kept; some summaries/source content were shortened."
        result["sources"] = [{key: value for key, value in item.items() if key != "content"} for item in result["sources"]]

    if args.format == "markdown":
        print("# Personal Context Read\n")
        print(f"Read level: {args.level}")
        print("\n## Seed records")
        for item in result["records"]:
            print(f"- `{item['id']}`: {item['summary']}")
        print("\n## Context candidates (model decides next)")
        for item in result["context_candidates"]:
            print(f"- `{item['id']}` [{item['candidate_tier']}]: {item['why_candidate']}; {item['summary']}")
        print("\n## Sources")
        for item in result["sources"]:
            print(f"- `{item['path']}`: {item.get('content', item.get('summary', ''))}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
