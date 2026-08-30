#!/usr/bin/env python3
"""Return a global survey, compatibility routing view, or complete audit catalog."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
from collections import defaultdict

from catalog_utils import build_catalog, build_catalog_header, route_catalog, write_catalog
from followup_check import check_followups
from v2_archive import load_v2, v2_audit


def compact_current_state(state: dict) -> dict:
    def trim(items: list) -> list:
        return [{"id": item.get("id"), "title": item.get("title"), "summary": (item.get("summary") or "")[:60]} for item in (items or [])]
    return {"as_of": state.get("as_of"), "core": trim(state.get("core")), "conditions": trim(state.get("conditions")), "tensions": trim(state.get("tensions")), "lived_examples": trim((state.get("lived_examples") or [])[:5]), "next": state.get("next", []), "format": state.get("format")}


def build_v2_survey(query: str = "") -> dict:
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
        by_phase[str(row.get("phase") or "未分期")].append(row)
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
    return {"version": "2.0.0", "schema": "life-spine + entity archive + contextual facets + current state + follow-up scheduler + causal hypotheses + knowledge cards", "spine": spine, "entities": entity_map, "facets": facet_map, "knowledge": knowledge, "current_state": state, "followups": check_followups(), "hypotheses": [{"id": row.get("id"), "claim": row.get("claim"), "status": row.get("status", "candidate"), "confidence": row.get("confidence")} for row in data.get("hypotheses", [])], "audit": v2_audit(), "note": "This is the compact routing map for v2: IDs, titles, labels, and counts only — no bodies or verbatim captures. After picking seeds, use retrieve_v2 --event-ids/--entity-ids for probe expansion; only deep reads verbatim captures. Facets from a single co-occurrence are omitted; probe fills them in via entity pairs. The spine buckets representatives by phase, so early periods (childhood, middle school, etc.) are not pushed out of the map by newer entries."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--view", choices=("survey", "routing", "full"), default="survey")
    parser.add_argument("--query", default="", help="Optional current user message for candidate ordering only.")
    parser.add_argument("--per-domain", type=int, default=4)
    parser.add_argument("--write", action="store_true", help="Explicitly rebuild memory/catalog.json and memory/catalog.md.")
    args = parser.parse_args()
    # survey is the light path run on every activation: it does not build the
    # full legacy record/source catalog (no hashing, no source matching).
    catalog = build_catalog_header() if args.view == "survey" else build_catalog()
    v2 = build_v2_survey(args.query)
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



