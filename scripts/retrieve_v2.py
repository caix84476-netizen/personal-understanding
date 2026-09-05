#!/usr/bin/env python3
"""Model-led retrieval for the v2 memory-shaped archive."""
from __future__ import annotations
from cli_runtime import CliReadGateError, configure_utf8_stdio, require_cli_capture
configure_utf8_stdio()
import argparse, json
from datetime import date, datetime
from collections import defaultdict
from catalog_utils import ROOT, anchor_ratio, content_terms, select_hypotheses, single_char_aliases, term_weights, weighted_match_score, weighted_query_terms
from v2_archive import V2_ROOT, followup_is_due, load_v2
import ppr


def haystack(row: dict) -> str:
    values = [str(row.get(key, "")) for key in ("id", "record_id", "title", "summary", "phase", "domain", "label", "context_key", "entry_kind")]
    values += [" ".join(row.get("aliases", []) or []), " ".join(row.get("entity_refs", []) or []), " ".join(row.get("related_entity_ids", []) or [])]
    return " ".join(values).casefold()


def title_haystack(row: dict) -> str:
    """Compact identity text (ids/title/label/aliases); matches there get a small
    bonus so records whose *title* names the concept beat long records that only
    mention it once in the body."""
    values = [str(row.get(key, "")) for key in ("id", "record_id", "title", "label")]
    values += [" ".join(row.get("aliases", []) or [])]
    return " ".join(values).casefold()


def row_score(row: dict, weights: dict[str, float]) -> float:
    return weighted_match_score(haystack(row), weights) + 0.5 * weighted_match_score(title_haystack(row), weights)


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
    ap.add_argument("--capture-id", default="", help="link this turn's verbatim capture into the retrieval trace; required for interactive reads unless --maintenance is set")
    ap.add_argument("--maintenance", action="store_true", help="declare a non-conversational read (rebuild/review/test) and skip the capture gate; audited, not silent")
    ap.add_argument("--no-trace", action="store_true", help="do not write a decision trace for this retrieval (default writes to memory/v2/traces/)")
    ap.add_argument("--format", choices=("json", "markdown"), default="json")
    args = ap.parse_args()
    try:
        require_cli_capture(args.capture_id, maintenance=args.maintenance, root=ROOT)
    except CliReadGateError as exc:
        print(str(exc), file=__import__("sys").stderr); return 2
    data = load_v2(); terms = weighted_query_terms(args.query)
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
    # Weighted ranking: IDF over the whole corpus so rare decisive terms (只狼/弦一郎)
    # outrank common chars, and length normalization so very long records stop dominating.
    # Curated single-char entity aliases (妈/爸) are referential, not noise: they keep
    # the multi-char weight so colloquial family queries can reach the entity→event feedback.
    alias_singles = single_char_aliases(entities)
    corpus = [haystack(row) for row in events] + [haystack(row) for row in entities] + [haystack(row) for row in knowledge]
    weights = term_weights(terms, corpus, alias_singles)
    content = content_terms(terms, alias_singles)

    def content_hit(row: dict) -> bool:
        """True when the row matches at least one signal-bearing query term. A row whose
        only hits are demoted single chars (a stray 防/钱/在) is a literal accident, not a
        retrieval result, and must not consume a budget slot. When the query itself has no
        content terms (e.g. a lone 烦) there is nothing to demand, so everything passes."""
        if not terms or not content:
            return True
        text = haystack(row)
        return any(t in text for t in content)

    entity_scores = {row.get("id"): row_score(row, weights) for row in entities}
    entity_content_ids = {row.get("id") for row in entities if row.get("id") in entity_scores and content_hit(row)}
    # Anchor demotion (catalog_utils.anchor_ratio): sentence-form queries carry many
    # incidental bigrams; only the query's rare decisive term anchors a relevant row.
    # Applies to the row's own text score — entity feedback keeps its full weight,
    # because a matched entity IS an anchor the query named.
    max_query_weight = max((weights.get(term, 0.0) for term in content), default=0.0)
    ENTITY_EVENT_BOOST = 0.6
    def event_value(row: dict) -> float:
        value = row_score(row, weights) * anchor_ratio(haystack(row), weights, content, max_query_weight)
        boost = max((entity_scores.get(ref, 0.0) for ref in row.get("entity_refs", []) if ref in entity_content_ids), default=0.0)
        return value + ENTITY_EVENT_BOOST * boost
    def qualifies(row: dict) -> bool:
        return content_hit(row) or bool(set(row.get("entity_refs", []) or []) & entity_content_ids)
    ranked_events = sorted(((event_value(row), row) for row in events), key=lambda pair: (-pair[0], -(pair[1].get("salience") or 0), pair[1].get("date_start") or "9999-99-99", pair[1].get("id", "")))
    selected_events = [row for _, row in ranked_events if row.get("id") in explicit_events or row.get("record_id") in explicit_events]
    selected_events += [row for value, row in ranked_events if row not in selected_events and (value > 0 and qualifies(row) or not terms or window)][: max(0, args.max_events - len(selected_events))]
    if not selected_events and explicit_events:
        selected_events = [row for row in events if row.get("id") in explicit_events or row.get("record_id") in explicit_events]
    event_ids = {row.get("id") for row in selected_events}
    entity_ids = set(explicit_entities)
    for row in selected_events: entity_ids.update(row.get("entity_refs", []))
    # Term-matched entities first; event-linked entities only fill the remaining budget.
    # (The old order did the opposite, so event-linked entities could exhaust the
    # budget and crowd out the entity the query actually named, e.g. 只狼.)
    ranked_entities = sorted(((row_score(row, weights), row) for row in entities), key=lambda pair: (-pair[0], pair[1].get("id", "")))
    selected_entities = [row for row in entities if row.get("id") in explicit_entities]
    selected_entities += [row for value, row in ranked_entities if value > 0 and content_hit(row) and row not in selected_entities][: max(0, args.max_entities - len(selected_entities))]
    if len(selected_entities) < args.max_entities:
        selected_entities += [row for row in entities if row.get("id") in entity_ids and row not in selected_entities][: max(0, args.max_entities - len(selected_entities))]
    entity_ids = {row.get("id") for row in selected_entities}
    ranked_knowledge = sorted(((row_score(row, weights) * anchor_ratio(haystack(row), weights, content, max_query_weight) + (7 if row.get("record_id") in explicit_events else 0), row) for row in knowledge), key=lambda pair: (-pair[0], -(pair[1].get("salience") or 0), pair[1].get("id", "")))
    selected_knowledge = [row for value, row in ranked_knowledge if row.get("record_id") in explicit_events]
    selected_knowledge += [row for value, row in ranked_knowledge if row not in selected_knowledge and ((value > 0 and content_hit(row)) or not terms)][:18]
    for row in selected_knowledge:
        entity_ids.update(row.get("entity_refs", []))
    # 2.6.0 associative side channel (SKILL §检索流程): spreading activation over the
    # archive graph, seeded by the entities the query actually named. Candidates land
    # in a separate `associations` section — never in the lexical timeline, never a
    # qualification on their own — so zero-overlap recall ("打击感烂" → 巫师3手感记录)
    # becomes reachable without polluting exact retrieval.
    assoc_adj = ppr.build_graph(events, entities, knowledge, facets)
    assoc_exclude = {row.get("record_id") for row in selected_events if row.get("record_id")}
    assoc_exclude |= {row.get("record_id") for row in selected_knowledge if row.get("record_id")}
    seed_weight_map = {row.get("id"): entity_scores.get(row.get("id"), 0.0) for row in entities if row.get("id") in entity_content_ids}
    association_rows = ppr.associations(assoc_adj, sorted(entity_content_ids), events, knowledge,
                                        exclude_record_ids=assoc_exclude, max_results=6,
                                        entity_rows=entities, seed_weights=seed_weight_map,
                                        query_terms=terms)
    selected_facets = [row for row in facets if set(row.get("entry_refs", [])) & event_ids or row.get("entity_id") in entity_ids or set(row.get("entity_ids", [])) & entity_ids]
    selected_facets = selected_facets[:40]
    selected_fragment_ids = set()
    seed_fragment_ids: set[str] = set()
    for row in selected_events:
        refs = set(row.get("fragment_refs", []))
        selected_fragment_ids.update(refs)
        if row.get("id") in explicit_events or row.get("record_id") in explicit_events:
            seed_fragment_ids.update(refs)
    for row in selected_entities:
        refs = set(row.get("fragment_refs", []))
        selected_fragment_ids.update(refs)
        if row.get("id") in explicit_entities:
            seed_fragment_ids.update(refs)
    for row in selected_knowledge:
        selected_fragment_ids.update(row.get("fragment_refs", []))
    selected_fragments = [fragments[fid] for fid in selected_fragment_ids if fid in fragments]
    # Deep means "go verify against the original words". The record the model
    # explicitly asked to verify outranks any neighbor's fragments, even when its
    # own evidence is summary_only — otherwise a legacy record's single fragment
    # gets crowded out of the 40-slot budget by the linked entities' verbatim
    # pool and deep answers a different record than the one queried.
    selected_fragments.sort(key=lambda row: (row.get("id") not in seed_fragment_ids, row.get("fidelity") != "verbatim", row.get("id", "")))
    if args.level == "probe": selected_fragments = []
    else: selected_fragments = selected_fragments[: args.max_fragments]
    followups = data.get("followups", [])
    today = date.today().isoformat()
    due = [row for row in followups if followup_is_due(row, today)]
    fidelity_by_fragment = {row.get("id"): row.get("fidelity") for row in data.get("fragments", [])}
    timeline_rows = [compact_event(row) for row in selected_events]
    for item, row in zip(timeline_rows, selected_events):
        item["evidence_fidelity"] = evidence_fidelity(row, fidelity_by_fragment)
    # Causal-hypothesis gate (SKILL.md: 普通事实问题不自动加载因果假设): a hypothesis
    # rides along only when the query's content terms hit its claim/scope/mechanism
    # text; otherwise the model sees none here and reaches for one deliberately via
    # the catalog stubs. Selection lives in catalog_utils (shared with the survey).
    all_hypotheses = data.get("hypotheses", [])
    carried_hypotheses = select_hypotheses(all_hypotheses, terms, content, weights)
    trace = {"activation": "retrieve", "level": args.level, "query": args.query, "window": args.window or None, "scoring": "weighted-idf-4-anchor+ppr", "survey": {"events": len(events), "entities": len(entities), "facets": len(facets)}, "selected": {"event_ids": [row.get("id") for row in selected_events], "entity_ids": [row.get("id") for row in selected_entities], "knowledge_ids": [row.get("id") for row in selected_knowledge], "facet_ids": [row.get("id") for row in selected_facets]}, "associations": {"seeds": sorted(entity_content_ids), "returned": len(association_rows), "via": [row.get("via_entity") for row in association_rows]}, "stopped": {"event_count": max(0, len(events) - len(selected_events)), "entity_count": max(0, len(entities) - len(selected_entities)), "reason": "Budget and relevance boundaries; the model must explicitly expand seeds when more is needed."}, "hypotheses": {"carried": len(carried_hypotheses), "omitted": max(0, len(all_hypotheses) - len(carried_hypotheses)), "policy": "content-term gate — 普通事实问题不自动加载因果假设"}, "fidelity": "probe does not read verbatim; deep reads only fragments linked to selected events/entities and preserves the summary_only marker."}
    trace_path = None
    if not args.no_trace:
        trace_path = save_trace(trace, capture_id=args.capture_id)
    result = {"retrieval_version": "2.6.0", "read": {"level": args.level, "query": args.query}, "timeline": timeline_rows, "entities": [compact_entity(row) for row in selected_entities], "knowledge": [row for row in selected_knowledge], "associations": association_rows, "facets": [compact_facet(row) for row in selected_facets], "current_state": data.get("current_state", {}), "followups": {"due": due}, "hypotheses": [{"id": row.get("id"), "claim": row.get("claim"), "scope": row.get("scope"), "mechanism": row.get("mechanism"), "status": row.get("status", "candidate"), "confidence": row.get("confidence")} for row in carried_hypotheses], "fragments": selected_fragments, "trace": trace, "trace_path": trace_path}
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
