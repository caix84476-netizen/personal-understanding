#!/usr/bin/env python3
"""Spreading-activation side channel: personalized PageRank over the archive graph.

The associative recall the user asked for (2026-09-05: "我真正想要的是这种检索") is
directional, not similarity-based: complaining about bad game feel should surface a
mouse complaint with ZERO lexical overlap, because both hang off the same abstract
node (操控体验). Lexical scoring can never see such targets — their score is 0.
This module is that second channel: seeds = entities the query already named, then
activation spreads along the archive's own graph (entity↔record refs, record↔record
relations, entity↔entity context co-membership). Output is a separate `associations`
section with the graph path kept visible — the model can judge the link instead of
trusting a bare similarity number. Zero dependencies; power iteration over a few
hundred nodes is sub-millisecond.

Border (SKILL §检索流程): associations NEVER enter the lexical timeline and never
qualify records by themselves. They ride in a clearly-labeled section so precise
recall stays exact and the associative channel stays auditable.
"""
from __future__ import annotations

from collections import defaultdict


def _bump(adj: dict[str, set[str]], a: str, b: str) -> None:
    if a and b and a != b:
        adj[a].add(b)
        adj[b].add(a)


def build_graph(events: list[dict], entities: list[dict], knowledge: list[dict], facets: list[dict] | None = None) -> dict[str, set[str]]:
    """Undirected adjacency: entities ↔ records (entity_refs), record ↔ record
    (related_ids/supersedes/contradicts/supports), entity ↔ entity (shared facet)."""
    adj: dict[str, set[str]] = defaultdict(set)
    for row in entities:
        eid = row.get("id")
        if not eid:
            continue
        for ref in (row.get("record_refs") or []) + (row.get("event_refs") or []) + (row.get("context_refs") or []):
            _bump(adj, eid, ref)
    for row in events:
        rid = row.get("id") or row.get("record_id")
        if not rid:
            continue
        for ref in row.get("entity_refs") or []:
            _bump(adj, rid, ref)
        rels = row.get("relation_refs") or {}
        for kind in ("related_ids", "supersedes", "supports"):
            for ref in rels.get(kind) or []:
                _bump(adj, rid, ref)
    for row in knowledge:
        rid = row.get("record_id")
        if not rid:
            continue
        for ref in row.get("entity_refs") or []:
            _bump(adj, rid, ref)
        rels = row.get("relation_refs") or {}
        for kind in ("related_ids", "supersedes", "supports"):
            for ref in rels.get(kind) or []:
                _bump(adj, rid, ref)
    for row in facets or []:
        members = set(row.get("entry_refs") or []) | set(row.get("entity_ids") or []) | ({row.get("entity_id")} if row.get("entity_id") else set())
        for a in members:
            for b in members:
                _bump(adj, a, b)
    return adj


def personalized_pagerank(adj: dict[str, set[str]], seeds: list[str], teleport: float = 0.15, iterations: int = 4) -> dict[str, float]:
    """Power-iteration PPR. Seeds equally weighted; unreachable nodes stay at 0.

    4 iterations ≈ 2-3 hop local spread, deliberately NOT a converged global
    rank: the archive has hub entities (ai-agi 68 mentions, home 63, … median 6)
    and a converged PPR lets them absorb all mass and spray it over every
    neighbour, turning "association" into generic popularity. Local spread keeps
    the candidates in the seed's actual neighbourhood."""
    seeds = [s for s in seeds if s in adj] or [s for s in seeds]
    if not seeds:
        return {}
    seed_set = set(seeds)
    rank = {node: (1.0 / len(seeds) if node in seed_set else 0.0) for node in adj}
    for _ in range(iterations):
        nxt = {node: 0.0 for node in adj}
        for node, score in rank.items():
            if not score:
                continue
            neighbours = adj.get(node) or ()
            if not neighbours:
                continue
            share = score * (1.0 - teleport) / len(neighbours)
            for nb in neighbours:
                nxt[nb] += share
        for node in seed_set:
            nxt[node] += teleport / len(seeds)
        rank = nxt
    return rank


def associations(adj: dict[str, set[str]], seeds: list[str], events: list[dict], knowledge: list[dict],
                 exclude_record_ids: set[str] | None = None, max_results: int = 6,
                 records_per_seed: int = 3, neighbour_mention_cap: int = 30,
                 entity_rows: list[dict] | None = None) -> list[dict]:
    """Associative candidates the lexical channels missed, in two tiers.

    Tier 1 — seed projections: records the query-named entities already carry at
    graph distance 1. 巫师3手感-anchored-by-RDR2 refs entity.game.steam-library; a
    打击感 query names steam-library lexically but its body text shares no term, so
    the record never rises lexically — the projection is exactly the recall the
    user described (2026-09-05 打击感/手感 example), distance 1, no hops needed.

    Tier 2 — spread neighbours: non-seed entities reachable in 2-3 hops that the
    query did NOT name, capped at neighbour_mention_cap mentions so the hub
    entities (ai-agi/home/mother, 50-68 mentions) cannot dress popularity up as
    association. Each carries its top record.

    Every row keeps its via-path; nothing here can qualify a record by itself."""
    if not seeds:
        return []
    exclude = set(exclude_record_ids or set())
    rank = personalized_pagerank(adj, seeds)
    seed_set = set(seeds)
    events_by_ref: dict[str, list[dict]] = defaultdict(list)
    for row in events:
        rid = row.get("record_id") or row.get("id")
        for ref in row.get("entity_refs") or []:
            events_by_ref[ref].append(row)
    knowledge_by_ref: dict[str, list[dict]] = defaultdict(list)
    for row in knowledge:
        rid = row.get("record_id")
        for ref in row.get("entity_refs") or []:
            knowledge_by_ref[ref].append(row)

    def records_of(node: str) -> list[tuple[str, dict, str]]:
        seen: set[str] = set()
        rows: list[tuple[int, str, dict, str]] = []
        for table, kind in ((events_by_ref, "event"), (knowledge_by_ref, "knowledge")):
            for row in table.get(node, []):
                rid = row.get("record_id") or row.get("id")
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                rows.append((-(row.get("salience") or 0), rid, row, kind))
        # salience-first: a seed entity's strongest facts must not be crowded out
        # of the projection budget by incidental event mentions
        rows.sort(key=lambda item: (item[0], item[1]))
        return [(rid, row, kind) for _, rid, row, kind in rows]

    mention = {row.get("id"): (row.get("mention_count") or 0) for row in entity_rows or []}
    candidates: list[dict] = []
    used: set[str] = set(exclude)

    def push(rid: str, row: dict, kind: str, via: str, spread: float) -> None:
        if rid in used:
            return
        used.add(rid)
        candidates.append({
            "record_id": rid, "kind": kind,
            "title": row.get("title") or "",
            "summary": (row.get("summary") or "")[:160],
            "via_entity": via, "seed_entities": list(seed_set),
            "spread_score": round(spread, 5),
        })

    # Tier 1: seed-entity projections — the seed's own strongest records.
    for seed in sorted(seed_set, key=lambda s: -rank.get(s, 0.0)):
        for rid, row, kind in records_of(seed)[:records_per_seed]:
            push(rid, row, kind, f"seed:{seed}", rank.get(seed, 0.0))
    # Tier 2: spread neighbours the query did not name, hubs capped out.
    neighbour_nodes = sorted(
        ((score, node) for node, score in rank.items()
         if node not in seed_set and node.startswith("entity.") and score > 0
         and mention.get(node, 0) <= neighbour_mention_cap),
        key=lambda pair: -pair[0])
    for score, node in neighbour_nodes:
        for rid, row, kind in records_of(node)[:1]:
            push(rid, row, kind, node, score)
            break
    # global spread order across both tiers before the budget cut
    candidates.sort(key=lambda item: -item["spread_score"])
    return candidates[:max_results]
