#!/usr/bin/env python3
"""Model-led retrieval for the v2 memory-shaped archive."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()
import argparse, json
from datetime import date, datetime
from collections import defaultdict
from catalog_utils import ROOT, query_terms
from v2_archive import V2_ROOT, followup_is_due, load_v2


def haystack(row: dict) -> str:
    values = [str(row.get(key, "")) for key in ("id", "record_id", "title", "summary", "phase", "domain", "label", "context_key", "entry_kind")]
    values += [" ".join(row.get("aliases", []) or []), " ".join(row.get("entity_refs", []) or []), " ".join(row.get("related_entity_ids", []) or [])]
    return " ".join(values).casefold()


def score(row: dict, terms: list[str]) -> int:
    text = haystack(row)
    return sum(1 for term in terms if term and term.casefold() in text)


def compact_event(row: dict) -> dict:
    return {key: row.get(key) for key in ("id", "record_id", "title", "summary", "date_text", "date_start", "date_end", "date_precision", "phase", "salience", "salience_label", "entry_kind", "entity_refs", "status", "confidence", "relation_refs")}


def compact_entity(row: dict) -> dict:
    return {key: row.get(key) for key in ("id", "label", "entity_type", "aliases", "mention_count", "record_refs", "event_refs", "context_refs")}


def compact_facet(row: dict) -> dict:
    return {key: row.get(key) for key in ("id", "label", "kind", "entity_id", "entity_ids", "context_key", "entry_refs", "related_entity_ids", "note")}


def evidence_fidelity(row: dict, fidelity_by_fragment: dict) -> dict:
    counts: dict[str, int] = {}
    for fragment_id in row.get("fragment_refs", []):
        fidelity = fidelity_by_fragment.get(fragment_id)
        if fidelity:
            counts[fidelity] = counts.get(fidelity, 0) + 1
    return counts


def save_trace(trace: dict, capture_id: str = "") -> str | None:
    """Append the retrieval decision trace to memory/v2/traces/; failures do not block retrieval."""
    try:
        traces = V2_ROOT / "traces"
        traces.mkdir(parents=True, exist_ok=True)
        row = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "capture_id": capture_id or None, **trace}
        path = traces / f"trace-{datetime.now():%Y%m}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return path.relative_to(ROOT).as_posix()
    except OSError as exc:
        print(f"Trace write failed (retrieval unaffected): {exc}", file=__import__("sys").stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query", default="")
    ap.add_argument("--event-ids", default="")
    ap.add_argument("--entity-ids", default="")
    ap.add_argument("--level", choices=("probe", "deep"), default="probe")
    ap.add_argument("--max-events", type=int, default=18)
    ap.add_argument("--max-entities", type=int, default=18)
    ap.add_argument("--max-fragments", type=int, default=40)
    ap.add_argument("--window", default="", help="time-window browsing, e.g. '2025-03' or '2025-03:2025-08'; combined with --query, filter by window first then rank by terms. For cold recall when keywords do not come to mind.")
    ap.add_argument("--capture-id", default="", help="link this turn's verbatim capture into the retrieval trace; optional")
    ap.add_argument("--no-trace", action="store_true", help="do not write a decision trace for this retrieval (default writes to memory/v2/traces/)")
    ap.add_argument("--format", choices=("json", "markdown"), default="json")
    args = ap.parse_args()
    data = load_v2(); terms = query_terms(args.query)
    events = [row for row in data.get("events", []) if row.get("status") not in {"archived", "deleted"}]
    window = str(args.window or "").strip()
    if window:
        parts = window.split(":", 1)
        lo = parts[0].strip()
        hi = parts[1].strip() if len(parts) > 1 and parts[1].strip() else lo + "~"
        lo = (lo + "-01-01")[:10] if len(lo) == 4 else (lo + "-01")[:10]
        hi = (hi + "-12-31")[:10] if len(hi) == 4 else (hi + "-31")[:10] if len(hi) == 7 else hi
        def in_window(row: dict) -> bool:
            start = str(row.get("date_start") or "")
            end = str(row.get("date_end") or start)
            return bool(start) and start[:len(hi)] <= hi and (end >= lo if len(end) == 10 else start >= lo[:len(start)])
        events = [row for row in events if in_window(row)]
    entities = data.get("entities", []); facets = data.get("contexts", []); knowledge = data.get("knowledge", []); fragments = {row.get("id"): row for row in data.get("fragments", [])}
    explicit_events = {x.strip() for x in args.event_ids.replace(";", ",").split(",") if x.strip()}
    explicit_entities = {x.strip() for x in args.entity_ids.replace(";", ",").split(",") if x.strip()}
    ranked_events = sorted(((score(row, terms), row) for row in events), key=lambda pair: (-pair[0], -(pair[1].get("salience") or 0), pair[1].get("date_start") or "9999-99-99", pair[1].get("id", "")))
    selected_events = [row for _, row in ranked_events if row.get("id") in explicit_events or row.get("record_id") in explicit_events]
    selected_events += [row for value, row in ranked_events if row not in selected_events and (value > 0 or not terms or window)][: max(0, args.max_events - len(selected_events))]
    if not selected_events and explicit_events:
        selected_events = [row for row in events if row.get("id") in explicit_events or row.get("record_id") in explicit_events]
    event_ids = {row.get("id") for row in selected_events}
    entity_ids = set(explicit_entities)
    for row in selected_events: entity_ids.update(row.get("entity_refs", []))
    ranked_entities = sorted(((score(row, terms) + (8 if row.get("id") in entity_ids else 0), row) for row in entities), key=lambda pair: (-pair[0], pair[1].get("id", "")))
    selected_entities = [row for _, row in ranked_entities if row.get("id") in entity_ids]
    selected_entities += [row for value, row in ranked_entities if row not in selected_entities and (value > 0 or not terms)][: max(0, args.max_entities - len(selected_entities))]
    entity_ids = {row.get("id") for row in selected_entities}
    ranked_knowledge = sorted(((score(row, terms) + (7 if row.get("record_id") in explicit_events else 0), row) for row in knowledge), key=lambda pair: (-pair[0], -(pair[1].get("salience") or 0), pair[1].get("id", "")))
    selected_knowledge = [row for value, row in ranked_knowledge if row.get("record_id") in explicit_events]
    selected_knowledge += [row for value, row in ranked_knowledge if row not in selected_knowledge and (value > 0 or not terms)][:18]
    for row in selected_knowledge:
        entity_ids.update(row.get("entity_refs", []))
    selected_facets = [row for row in facets if set(row.get("entry_refs", [])) & event_ids or row.get("entity_id") in entity_ids or set(row.get("entity_ids", [])) & entity_ids]
    selected_facets = selected_facets[:40]
    selected_fragment_ids = set()
    for row in selected_events:
        selected_fragment_ids.update(row.get("fragment_refs", []))
    for row in selected_entities:
        selected_fragment_ids.update(row.get("fragment_refs", []))
    for row in selected_knowledge:
        selected_fragment_ids.update(row.get("fragment_refs", []))
    selected_fragments = [fragments[fid] for fid in selected_fragment_ids if fid in fragments]
    selected_fragments.sort(key=lambda row: (row.get("fidelity") != "verbatim", row.get("id", "")))
    if args.level == "probe": selected_fragments = []
    else: selected_fragments = selected_fragments[: args.max_fragments]
    followups = data.get("followups", [])
    today = date.today().isoformat()
    due = [row for row in followups if followup_is_due(row, today)]
    fidelity_by_fragment = {row.get("id"): row.get("fidelity") for row in data.get("fragments", [])}
    timeline_rows = [compact_event(row) for row in selected_events]
    for item, row in zip(timeline_rows, selected_events):
        item["evidence_fidelity"] = evidence_fidelity(row, fidelity_by_fragment)
    trace = {"activation": "retrieve", "level": args.level, "query": args.query, "window": args.window or None, "survey": {"events": len(events), "entities": len(entities), "facets": len(facets)}, "selected": {"event_ids": [row.get("id") for row in selected_events], "entity_ids": [row.get("id") for row in selected_entities], "knowledge_ids": [row.get("id") for row in selected_knowledge], "facet_ids": [row.get("id") for row in selected_facets]}, "stopped": {"event_count": max(0, len(events) - len(selected_events)), "entity_count": max(0, len(entities) - len(selected_entities)), "reason": "Budget and relevance boundaries; the model must explicitly expand seeds when more is needed."}, "fidelity": "probe does not read verbatim; deep reads only fragments linked to selected events/entities and preserves the summary_only marker."}
    trace_path = None
    if not args.no_trace:
        trace_path = save_trace(trace, capture_id=args.capture_id)
    result = {"retrieval_version": "2.0.0", "read": {"level": args.level, "query": args.query}, "timeline": timeline_rows, "entities": [compact_entity(row) for row in selected_entities], "knowledge": [row for row in selected_knowledge], "facets": [compact_facet(row) for row in selected_facets], "current_state": data.get("current_state", {}), "followups": {"due": due}, "hypotheses": data.get("hypotheses", []), "fragments": selected_fragments, "trace": trace, "trace_path": trace_path}
    if args.format == "markdown":
        print("# v2 Personal Understanding Read")
        print(f"Read level: {args.level}; query: {args.query or 'global spine'}\n")
        print("## Timeline entries")
        for row in result["timeline"]: print(f"- `{row['date_text']}` [{row['salience_label']}] {row['title']}")
        print("\n## Entities")
        for row in result["entities"]: print(f"- `{row['id']}`: {row['label']}")
        if args.level == "deep":
            print("\n## Verbatim/evidence fragments")
            for row in selected_fragments: print(f"- [{row.get('fidelity')}] {row.get('verbatim','')}")
    else: print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
