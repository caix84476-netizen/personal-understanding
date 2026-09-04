#!/usr/bin/env python3
"""Return a global survey, compatibility routing view, or complete audit catalog."""
from __future__ import annotations
from cli_runtime import CliReadGateError, configure_utf8_stdio, require_cli_capture
configure_utf8_stdio()

import argparse
import json
from collections import defaultdict

from catalog_utils import ROOT, build_catalog, build_catalog_header, content_terms, route_catalog, select_hypotheses, single_char_aliases, weighted_query_terms, write_catalog
from followup_check import check_followups
from v2_archive import load_v2, v2_audit


def compact_current_state(state: dict) -> dict:
    def trim(items: list) -> list:
        return [{"id": item.get("id"), "title": item.get("title"), "summary": (item.get("summary") or "")[:60]} for item in (items or [])]
    return {"as_of": state.get("as_of"), "core": trim(state.get("core")), "conditions": trim(state.get("conditions")), "tensions": trim(state.get("tensions")), "lived_examples": trim((state.get("lived_examples") or [])[:5]), "next": state.get("next", []), "format": state.get("format")}


def build_v2_survey(query: str = "", gate_hypotheses: bool = True) -> dict:
    data = load_v2()
    events = [row for row in data.get("events", []) if row.get("status") not in {"archived", "deleted"}]
    entities = data.get("entities", [])
    contexts = data.get("contexts", [])
    anchors = [row for row in events if int(row.get("salience", 0) or 0) >= 2]
    if not anchors:
        anchors = events
    # Bucket by phase and take representatives from each period so the spine is
    # not dominated by the most recent entries (recency bias): per phase take
    # the highest-salience items, top up to the minimum, then sort by time.
    by_phase: dict[str, list] = defaultdict(list)
    for row in anchors:
        # projection already normalizes the literal "None" phase (normalized_phase
        # in v2_archive); the fallback here only guards legacy caches built before 2.5.0.
        phase_value = str(row.get("phase") or "未分期")
        by_phase["未分期" if phase_value == "None" else phase_value].append(row)
    per_phase = max(10, min(20, 60 // max(1, len(by_phase))))
    weight_key = lambda row: (-int(row.get("salience", 0) or 0), str(row.get("date_start") or "9999-99-99"), str(row.get("id", "")))
    selected: list = []
    for phase in sorted(by_phase):
        selected.extend(sorted(by_phase[phase], key=weight_key)[:per_phase])
    if len(selected) < 50:
        chosen = {row.get("id") for row in selected}
        rest = sorted((row for row in anchors if row.get("id") not in chosen), key=weight_key)
        selected.extend(rest[: 50 - len(selected)])
    selected.sort(key=lambda row: (str(row.get("date_start") or "9999-99-99"), -int(row.get("salience", 0) or 0), str(row.get("id", ""))))
    spine = [{key: row.get(key) for key in ("id", "title", "date_text", "phase", "salience", "salience_label", "entry_kind", "entity_refs", "status")} for row in selected[:60]]
    entity_map = [{"id": row.get("id"), "label": row.get("label"), "entity_type": row.get("entity_type"), "aliases": (row.get("aliases") or [])[:6], "mention_count": row.get("mention_count"), "story_count": len(row.get("event_refs", [])) + len(row.get("fragment_refs", []))} for row in entities]
    facet_map = []
    for row in contexts:
        entry_count = len(row.get("entry_refs", []))
        if row.get("kind") != "facet" or entry_count < 2:
            continue
        facet_map.append({"id": row.get("id"), "label": row.get("label"), "kind": row.get("kind"), "entity_ids": row.get("entity_ids"), "entry_count": entry_count})
    knowledge = [{key: row.get(key) for key in ("id", "kind", "title", "domain", "salience_label")} for row in data.get("knowledge", []) if row.get("status") not in {"archived", "deleted"} and (row.get("kind") in {"model", "value"} or int(row.get("salience", 0) or 0) >= 2)]
    state = compact_current_state(data.get("current_state", {}))
    # Causal-hypothesis gate (shared with retrieve_v2, see catalog_utils): claim/scope/
    # mechanism travel only when the query's content terms hit the hypothesis text.
    # Everything else stays a claim-less stub so the model knows it exists without the
    # causal content loading itself into an ordinary read. --view full is the explicit
    # "complete catalog" maintenance read, so it bypasses the gate (gate_hypotheses=False).
    hypo_rows = data.get("hypotheses", [])
    if gate_hypotheses:
        query_terms = weighted_query_terms(query)
        matched_ids = {row.get("id") for row in select_hypotheses(hypo_rows, query_terms, content_terms(query_terms, single_char_aliases(entities)))}
        hypotheses_map = [{"id": row.get("id"), "claim": row.get("claim"), "scope": row.get("scope"), "mechanism": row.get("mechanism"), "status": row.get("status", "candidate"), "confidence": row.get("confidence")} if row.get("id") in matched_ids else {"id": row.get("id"), "status": row.get("status", "candidate"), "confidence": row.get("confidence")} for row in hypo_rows]
        hypo_note = "Causal hypotheses carry claim/scope/mechanism only when the current query's content terms hit them (普通事实问题不自动加载因果假设); claim-less entries are routing stubs — read the full row via --view full (maintenance) or a query that names the concern."
    else:
        hypotheses_map = [{"id": row.get("id"), "claim": row.get("claim"), "scope": row.get("scope"), "mechanism": row.get("mechanism"), "status": row.get("status", "candidate"), "confidence": row.get("confidence")} for row in hypo_rows]
        hypo_note = "Causal hypotheses are shown in full: --view full is the explicit complete-catalog maintenance read."
    return {"version": "2.0.0", "schema": "life-spine + entity archive + contextual facets + current state + follow-up scheduler + causal hypotheses + knowledge cards", "spine": spine, "entities": entity_map, "facets": facet_map, "knowledge": knowledge, "current_state": state, "followups": check_followups(), "hypotheses": hypotheses_map, "audit": v2_audit(), "note": "This is the compact routing map for v2: IDs, titles, labels, and counts only — no bodies or verbatim captures. After picking seeds, use retrieve_v2 --event-ids/--entity-ids for probe expansion; only deep reads verbatim captures. Facets from a single co-occurrence are omitted; probe fills them in via entity pairs. The spine buckets representatives by phase, so early periods (childhood, middle school, etc.) are not pushed out of the map by newer entries. " + hypo_note}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--view", choices=("survey", "routing", "full"), default="survey")
    parser.add_argument("--query", default="", help="Optional current user message for candidate ordering only.")
    parser.add_argument("--per-domain", type=int, default=4)
    parser.add_argument("--write", action="store_true", help="Explicitly rebuild memory/catalog.json and memory/catalog.md. Implies --maintenance.")
    parser.add_argument("--capture-id", default="", help="link this turn's verbatim capture; required for interactive survey/routing reads unless --maintenance/--write is set")
    parser.add_argument("--maintenance", action="store_true", help="declare a non-conversational read (rebuild/review/test) and skip the capture gate")
    args = parser.parse_args()
    # --write is a maintenance rebuild by definition; treat it as self-declaring
    # --maintenance so the internal rebuild path never trips its own gate.
    maintenance = args.maintenance or args.write
    try:
        require_cli_capture(args.capture_id, maintenance=maintenance, root=ROOT)
    except CliReadGateError as exc:
        print(str(exc), file=__import__("sys").stderr); return 2
    # survey is the light path run on every activation: it does not build the
    # full legacy record/source catalog (no hashing, no source matching).
    # --write persists the full catalog, which the light header cannot supply
    # (no `records` key) — so writing always builds the full catalog regardless
    # of view (2.5.0 latent bug: `--view survey --write` crashed on KeyError
    # since the 2.4.0 light-header split; only rebuild_views used the full path).
    if args.write:
        catalog = build_catalog()
    else:
        catalog = build_catalog_header() if args.view == "survey" else build_catalog()
    v2 = build_v2_survey(args.query, gate_hypotheses=(args.view != "full"))
    if args.write:
        write_catalog(catalog)
    if args.view == "full":
        result = {**catalog, "v2": v2}
    elif args.view == "routing":
        result = {**route_catalog(catalog, args.query, max(1, args.per_domain)), "v2": v2}
    else:
        result = {
            "catalog_version": catalog["catalog_version"],
            "view": "survey",
            "query": args.query,
            "policy": catalog["policy"],
            "decision_contract": catalog["decision_contract"],
            "counts": catalog["counts"],
            "survey_counts": catalog["survey"]["counts"],
            "survey_note": "survey is a compact routing map: it contains only the v2 timeline spine, the entity/context catalog, current state, and follow-ups; it does not expand the full legacy record list or raw source bodies. Use --view routing to expand the legacy catalog by domain, or --view full for the complete catalog.",
            "v2": v2,
        }
    if args.format == "markdown":
        print("# Personal memory global survey\n" if args.view == "survey" else "# Personal memory routing catalog\n" if args.view == "routing" else "# Full personal memory catalog\n")
        print(f"Records: {catalog['counts']['records']}; sources: {catalog['counts']['sources']}; branches: {catalog['counts']['branches']}")
        if args.view == "survey":
            print(f"\n{catalog['survey']['counts']['current']} current records / {catalog['survey']['counts']['history']} history index entries (full lists in --view routing/full; this view outputs only the v2 routing map)")
        elif args.view == "routing":
            for domain in result["domains"]:
                print(f"\n## {domain['id']}")
                for item in domain["records"]:
                    print(f"- `{item['id']}`: {item['summary']}")
        else:
            for item in catalog["branches"]:
                print(f"- `{item['id']}`: {item['summary']}")
        print("\n## v2 memory spine")
        print(f"- Timeline entries: {len(v2['spine'])}; entities: {len(v2['entities'])}; context cards: {len(v2['facets'])}")
        print(f"- Follow-ups: {len(v2['followups']['due'])} due; {len(v2['followups']['undated_pending'])} missing a date")
    elif args.view == "survey":
        # Survey is the per-turn global map the model must read whole; compact
        # JSON keeps it inside a reasonable context budget. Other views stay pretty.
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



