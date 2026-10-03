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
    # 2.7.0: summary cap 60 → 48 chars and lived_examples 5 → 3 — this card is
    # embedded in every view and every retrieval (measured 8.4KB serialized).
    def trim(items: list) -> list:
        return [{"id": item.get("id"), "title": item.get("title"), "summary": (item.get("summary") or "")[:48]} for item in (items or [])]
    return {"as_of": state.get("as_of"), "core": trim(state.get("core")), "conditions": trim(state.get("conditions")), "tensions": trim(state.get("tensions")), "lived_examples": trim((state.get("lived_examples") or [])[:3]), "next": state.get("next", []), "format": state.get("format")}


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
    spine = [{key: (row.get(key)[:3] if key == "entity_refs" and isinstance(row.get(key), list) else row.get(key)) for key in ("id", "title", "date_text", "phase", "salience", "salience_label", "entry_kind", "entity_refs", "status")} for row in selected[:60]]
    # 2.7.0 size budget: the survey is read whole every turn, so every section is
    # capped at build time — measured 2026-09-25, facets alone were 45KB and grew
    # with the archive. Heads are kept by signal strength (entry_count /
    # mention_count), probes fill the rest in on demand.
    facets_sorted = sorted(
        (row for row in contexts if row.get("kind") == "facet" and len(row.get("entry_refs", [])) >= 2),
        key=lambda row: -len(row.get("entry_refs", [])))
    facet_map = [{"id": row.get("id"), "label": row.get("label"), "kind": row.get("kind"), "entity_ids": row.get("entity_ids"), "entry_count": len(row.get("entry_refs", []))} for row in facets_sorted[:40]]
    entity_map = [{"id": row.get("id"), "label": row.get("label"), "entity_type": row.get("entity_type"), "aliases": (row.get("aliases") or [])[:6], "mention_count": row.get("mention_count"), "story_count": len(row.get("event_refs", [])) + len(row.get("fragment_refs", []))} for row in sorted(entities, key=lambda row: -(row.get("mention_count") or 0))[:60]]
    knowledge = [{key: row.get(key) for key in ("id", "kind", "title", "domain", "salience_label")} for row in data.get("knowledge", []) if row.get("status") not in {"archived", "deleted"} and (row.get("kind") in {"model", "value"} or int(row.get("salience", 0) or 0) >= 2)][:40]
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


# 2.7.0 budgets calibrated to measured floors on the live archive (2026-09-25,
# plan-exhausted floors: routing 52.6K / full 76.1K / survey 27.2K — see the
# fit_budget comment): routing/full rose from the aspirational 64K because the
# honest floor of a complete map is what it is; a budget below the floor would
# truncate every read and make the metadata meaningless.
VIEW_BUDGET_DEFAULTS = {"survey": 48_000, "routing": 68_000, "full": 96_000}


def fit_budget(result: dict, budget: int, pretty: bool) -> tuple[str, dict]:
    """Deterministic overflow shrinking (2.7.0). Views used to serialize unbounded:
    measured 2026-09-25 on the live archive, one routing response hit 1.27MB and
    full 1.77MB — far past what any model can ingest. Shrinking order is fixed
    (largest measured sections first), each step keeps the HEAD of the list (the
    ranked/representative part) and counts the omission into result["budget"].
    If the whole plan bottoms out still over budget, the JSON stays VALID and
    carries budget metadata instead of being cut mid-structure — a parseable
    over-budget response beats an unparseable truncated one; mcp_server's 200K
    text_result guard remains the last-resort backstop."""
    omitted: dict[str, int] = {}
    budget_meta: dict = {"max_chars": budget}

    def serialize() -> str:
        return json.dumps(result, ensure_ascii=False, indent=(2 if pretty else None))

    def cap(path: tuple[str, ...], limit: int) -> None:
        node = result
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                return
        if not isinstance(node, dict):
            return
        rows = node.get(path[-1])
        if isinstance(rows, list) and len(rows) > limit:
            label = ".".join(path)
            omitted[label] = omitted.get(label, 0) + len(rows) - limit
            node[path[-1]] = rows[:limit]

    def cap_each_domain(limit: int) -> None:
        for domain in result.get("domains") or []:
            rows = domain.get("records")
            if isinstance(rows, list) and len(rows) > limit:
                label = f"domains[{domain.get('id')}].records"
                omitted[label] = omitted.get(label, 0) + len(rows) - limit
                domain["records"] = rows[:limit]

    plan = [
        lambda: cap(("survey", "current"), 60),
        lambda: cap(("survey", "history"), 60),
        lambda: cap(("sources",), 24),
        lambda: cap(("records",), 250),
        lambda: cap_each_domain(24),
        lambda: cap(("v2", "spine"), 45),
        lambda: cap(("v2", "entities"), 30),
        lambda: cap(("v2", "facets"), 20),
        lambda: cap(("v2", "knowledge"), 20),
        lambda: cap(("survey", "current"), 20),
        lambda: cap(("survey", "history"), 10),
        lambda: cap(("sources",), 12),
        lambda: cap(("records",), 120),
        lambda: cap_each_domain(8),
        lambda: cap(("v2", "spine"), 30),
        lambda: cap(("v2", "entities"), 20),
        lambda: cap(("v2", "facets"), 15),
        lambda: cap(("v2", "knowledge"), 15),
        lambda: cap_each_domain(4),
        lambda: cap(("records",), 60),
        lambda: cap(("sources",), 6),
        lambda: cap_each_domain(2),
        lambda: cap(("records",), 30),
        # 2.7.0 final floor tier: measured bottoms-out floors were routing 70K /
        # full 103K against 68K/96K budgets — this tier closes the gap so the
        # budgets stay reachable and the truncated metadata stays honest.
        lambda: cap(("v2", "spine"), 24),
        lambda: cap(("v2", "entities"), 16),
        lambda: cap(("v2", "facets"), 12),
        lambda: cap(("v2", "knowledge"), 12),
        lambda: cap(("survey", "current"), 14),
        lambda: cap(("survey", "history"), 6),
        lambda: cap_each_domain(1),
        lambda: cap(("sources",), 4),
        lambda: cap(("records",), 20),
    ]
    text = serialize()
    if len(text) > budget:
        for step in plan:
            if len(text) <= budget:
                break
            step()
            text = serialize()
        budget_meta.update({"truncated": True, "omitted": omitted, "final_chars": len(text)})
        result["budget"] = budget_meta
        text = serialize()
    return text, budget_meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--view", choices=("survey", "routing", "full"), default="survey")
    parser.add_argument("--query", default="", help="Optional current user message for candidate ordering only.")
    parser.add_argument("--per-domain", type=int, default=4)
    parser.add_argument("--domain", default="", help="filter routing/full to one branch id (e.g. domain.family-home); survey ignores it")
    parser.add_argument("--max-chars", type=int, default=0, help="output budget in characters; 0 = view default (survey 48K, routing 68K, full 96K)")
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
    domain_filter = args.domain.strip()
    if args.view == "full":
        if domain_filter:
            catalog = {**catalog, "records": [item for item in catalog.get("records", []) if item.get("domain") == domain_filter]}
            if domain_filter not in {b.get("id") for b in catalog.get("branches", [])}:
                catalog["branches"] = [b for b in catalog.get("branches", []) if b.get("id") == domain_filter]
        result = {**catalog, "v2": v2}
    elif args.view == "routing":
        routed = route_catalog(catalog, args.query, max(1, args.per_domain))
        if domain_filter:
            routed["domains"] = [d for d in routed.get("domains", []) if d.get("id") == domain_filter]
        result = {**routed, "v2": v2}
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
        text, _budget = fit_budget(result, args.max_chars or VIEW_BUDGET_DEFAULTS["survey"], pretty=False)
        print(text)
    else:
        text, _budget = fit_budget(result, args.max_chars or VIEW_BUDGET_DEFAULTS[args.view], pretty=True)
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



