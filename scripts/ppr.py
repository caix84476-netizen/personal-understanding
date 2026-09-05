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
        for ref in row.get("related_ids") or []:
            # card 挂靠边（2.6.0）：概念卡 frontmatter 声明的挂靠记录是真语义边，
            # 不是共现——没有它，概念卡是扩散进得去、走不出来的孤岛。
            _bump(adj, eid, ref)
    for row in events:
        rid = row.get("id") or row.get("record_id")
        if not rid:
            continue
        for ref in row.get("entity_refs") or []:
            _bump(adj, rid, ref)
        rels = row.get("relation_refs") or {}
        for kind in ("related_ids", "supersedes", "supports", "contradicts"):
            for ref in rels.get(kind) or []:
                _bump(adj, rid, ref)
    for row in knowledge:
        rid = row.get("record_id")
        if not rid:
            continue
        for ref in row.get("entity_refs") or []:
            _bump(adj, rid, ref)
        rels = row.get("relation_refs") or {}
        for kind in ("related_ids", "supersedes", "supports", "contradicts"):
            for ref in rels.get(kind) or []:
                _bump(adj, rid, ref)
    for row in facets or []:
        members = set(row.get("entry_refs") or []) | set(row.get("entity_ids") or []) | ({row.get("entity_id")} if row.get("entity_id") else set())
        for a in members:
            for b in members:
                _bump(adj, a, b)
    return adj


def personalized_pagerank(adj: dict[str, set[str]], seeds: list[str], teleport: float = 0.15, iterations: int = 4, seed_weights: dict[str, float] | None = None) -> dict[str, float]:
    """Power-iteration PPR. Unreachable nodes stay at 0.

    4 iterations ≈ 2-3 hop local spread, deliberately NOT a converged global
    rank: the archive has hub entities (ai-agi 68 mentions, home 63, … median 6)
    and a converged PPR lets them absorb all mass and spray it over every
    neighbour, turning "association" into generic popularity. Local spread keeps
    the candidates in the seed's actual neighbourhood. (Prior art: HippoRAG's
    run_ppr uses damping 0.5 on the undirected projection — an even more
    aggressive locality knob; we reach the same effect via low iteration count
    on stdlib. 2.6.1: seeds may carry non-uniform reset weights — the query's
    lexical hit strength decides which seed dominates the spread, as HippoRAG
    does with its reset_prob vector.)"""
    seed_weights = seed_weights or {}
    seeds = [s for s in seeds if s in adj] or [s for s in seeds]
    if not seeds:
        return {}
    seed_set = set(seeds)
    raw = {s: max(float(seed_weights.get(s, 0.0)), 0.0) for s in seeds}
    if sum(raw.values()) <= 0:
        raw = {s: 1.0 for s in seeds}
    total = sum(raw.values())
    rank = {node: (raw[node] / total if node in seed_set else 0.0) for node in adj}
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
                 entity_rows: list[dict] | None = None, seed_weights: dict[str, float] | None = None,
                 query_terms: list[str] | None = None) -> list[dict]:
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
    rank = personalized_pagerank(adj, seeds, seed_weights=seed_weights)
    query_terms = query_terms or []
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

    query_hit_terms = {t.casefold() for t in (query_terms or []) if len(t) >= 2}

    def records_of(node: str) -> list[tuple[str, dict, str]]:
        seen: set[str] = set()
        rows: list[tuple[int, str, dict, str]] = []
        for table, kind in ((events_by_ref, "event"), (knowledge_by_ref, "knowledge")):
            for row in table.get(node, []):
                rid = row.get("record_id") or row.get("id")
                if not rid or rid in seen:
                    continue
                # 万能邻居治理（2.6.1，g05/g10/g14 实测）：一条记录挂靠 >10 个实体
                # 意味着它"什么都沾"，在联想层是万能噪声（skill 元讨论、泛化纠正）。
                # 词面通道仍可命中它们；这里只让联想候选保持具体。
                if len(row.get("entity_refs") or []) > 10:
                    continue
                seen.add(rid)
                rows.append((-(row.get("salience") or 0), rid, row, kind))
        # salience-first, then query-relevance: a seed entity's strongest facts must
        # not be crowded out of the projection budget, but among equal salience the
        # record whose text actually shares query words outranks a merely-adjacent
        # one (2.6.1, h05 实测：相邻但内容无关的记录曾占据联想名额).
        def relevance(item):
            _, rid, row, kind = item
            text = f"{row.get('title','')} {row.get('summary','')}".casefold()
            return sum(1 for term in query_hit_terms if term in text)
        declared_rank = {rid: i for i, rid in enumerate((entity_row_by_id.get(node) or {}).get("related_ids") or [])}
        rows.sort(key=lambda item: (
            0 if item[1] in declared_rank else 1,   # 声明挂靠无条件优先于"碰巧提及"
            item[0], -relevance(item), declared_rank.get(item[1], 99), item[1]))
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
    # 同分 tiebreak 用卡片挂靠声明序（related_ids 顺序=写卡时的语义优先序），
    # 不用 id 字母序：字母序系统性偏向 event.*，会把卡片置顶的规则/边界记录
    # （pref.*）挤出投影名额——实测"推荐游戏"场景晕3D硬规则因此不可达。
    entity_row_by_id = {row.get("id"): row for row in entity_rows or []}
    for seed in sorted(seed_set, key=lambda s: -rank.get(s, 0.0)):
        declared = {rid: i for i, rid in enumerate((entity_row_by_id.get(seed) or {}).get("related_ids") or [])}
        projected = sorted(records_of(seed),
                           key=lambda item: (-(item[1].get("salience") or 0), declared.get(item[0], 99), item[0]))
        for rid, row, kind in projected[:records_per_seed]:
            push(rid, row, kind, f"seed:{seed}", rank.get(seed, 0.0))
    # Tier 2: spread neighbours the query did not name, hubs capped out.
    # SYNAPSE (ACL 2026) gates propagation with a sigmoid activation
    # σ(γ(s-θ)), γ=5, θ=0.5 — activation below the cognitive threshold is
    # damped, not hard-cut. We gate each neighbour by its spread relative to
    # the strongest neighbour: nodes the user would not actually "think of"
    # crush to the tail instead of occupying slots by mere positivity.
    neighbour_scores = [(score, node) for node, score in rank.items()
                        if node not in seed_set and node.startswith("entity.") and score > 0
                        and mention.get(node, 0) <= neighbour_mention_cap]
    strongest = max((s for s, _ in neighbour_scores), default=0.0)
    def _gate(s: float) -> float:
        if strongest <= 0: return 1.0
        return 1.0 / (1.0 + 2.718281828459045 ** (-5.0 * (s / strongest - 0.5)))
    neighbour_nodes = sorted(
        ((_gate(s), s, node) for s, node in neighbour_scores),
        key=lambda triple: (-triple[0], -triple[1]))
    for gate_value, score, node in neighbour_nodes:
        for rid, row, kind in records_of(node)[:1]:
            push(rid, row, kind, node, score * gate_value)
            break
    # global spread order across both tiers before the budget cut
    candidates.sort(key=lambda item: -item["spread_score"])
    return candidates[:max_results]
