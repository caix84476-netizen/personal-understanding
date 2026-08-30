#!/usr/bin/env python3
"""Legacy deterministic retrieval for explicit query fallback.

Normal activation is model-led: use ``preflight_context.py`` followed by
``catalog_context.py`` and ``retrieve_context.py``. This script remains useful
for exact keyword fallback and regression probes, but fixed proactive cues are
not part of the default runtime path.
"""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "memory" / "records"
BRANCHES = ROOT / "memory" / "branches"
PROACTIVE_CUES = ROOT / "references" / "proactive-cues.json"
CORE_KINDS = {"state", "value", "rule", "heuristic", "model", "preference", "decision"}
EVIDENCE_KINDS = {"event", "fact", "entity"}


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                body_start = i + 1
                break
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[body_start:]).strip()


def split_ids(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[;,]", value or "") if x.strip() and x.strip().lower() not in {"none", "null"}]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def query_terms(query: str) -> list[str]:
    q = normalize(query)
    terms = set(re.findall(r"[a-z0-9][a-z0-9_.-]+|[\u4e00-\u9fff]{2,}", q))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", q):
        # Long Chinese runs are also searched by useful 2-4 character windows.
        for n in (4, 3, 2):
            terms.update(chunk[i:i+n] for i in range(max(0, len(chunk)-n+1)))
    return sorted((x for x in terms if len(x) >= 2), key=lambda x: (-len(x), x))


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    m = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})", value)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{4})[-年](\d{1,2})", value.strip())
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.fullmatch(r"\d{4}", value.strip())
    if m:
        return date(int(value), 1, 1)
    return None


def date_limit(args: argparse.Namespace) -> tuple[date | None, date | None, date | None]:
    return parse_date(args.since), parse_date(args.until), parse_date(args.as_of)


def in_time(meta: dict[str, str], args: argparse.Namespace) -> bool:
    since, until, as_of = date_limit(args)
    start = parse_date(meta.get("valid_from") or meta.get("last_confirmed"))
    end = parse_date(meta.get("valid_until"))
    if as_of and start and start > as_of:
        return False
    if as_of and end and end < as_of:
        return False
    if since and end and end < since:
        return False
    if until and start and start > until:
        return False
    return True


def record_text(meta: dict[str, str], body: str, path: Path) -> str:
    # cue_terms are latent routing hints, not explicit user-facing matches.
    # Keeping them out of the direct haystack makes the result explainable:
    # a record is either named/quoted by the query, or retrieved proactively.
    fields = [path.stem, body, *(value for key, value in meta.items() if key != "cue_terms")]
    return normalize(" ".join(fields))


def score_terms(terms: list[str], haystack: str, meta: dict[str, str], query: str) -> int:
    score = 0
    record_id = normalize(meta.get("id", ""))
    aliases = normalize(meta.get("aliases", ""))
    for term in terms:
        if term in record_id:
            score += 5
        elif term in aliases:
            # Explicit names supplied by the user outrank generic cue matches.
            score += 4
        elif term in normalize(meta.get("domain", "")):
            score += 4
        elif term in haystack and (len(term) >= 3 or term in aliases):
            # Two-character Chinese windows are useful for expansion but too
            # noisy as direct evidence; require a declared alias for them.
            score += 1
    q = normalize(query)
    if any(x in q for x in ("当前", "现在", "目前", "最新", "如今")) and meta.get("kind") == "state":
        score += 3
    if any(x in q for x in ("选择", "决定", "取舍", "应该", "怎么办", "职业", "专业")) and meta.get("kind") in {"value", "rule", "heuristic", "decision", "model"}:
        score += 2
        # Decision questions need the user's heuristics and values, not only
        # the newest state record. Give those layers room under tight budgets.
        score += {"heuristic": 6, "value": 4, "rule": 4, "model": 2}.get(meta.get("kind"), 0)
    if any(x in q for x in ("时间", "经历", "当时", "以前", "历史", "过程")) and meta.get("kind") == "event":
        score += 2
    return score


def load_proactive_cues() -> list[dict[str, object]]:
    if not PROACTIVE_CUES.exists():
        return []
    try:
        data = json.loads(PROACTIVE_CUES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def proactive_signals(query: str, rules: list[dict[str, object]]) -> list[dict[str, object]]:
    q = normalize(query)
    signals: list[dict[str, object]] = []
    for rule in rules:
        triggers = [normalize(str(x)) for x in rule.get("triggers", [])]
        matched = [x for x in triggers if x and x in q]
        if matched:
            signals.append({
                "signal": rule.get("signal", "unknown"),
                "matched": matched[:4],
                "expansions": [str(x) for x in rule.get("expansions", [])],
            })
    return signals


def score_proactive(signals: list[dict[str, object]], row: dict[str, object]) -> int:
    if not signals:
        return 0
    meta = row["meta"]
    searchable = row["text"]
    cue_terms = normalize(meta.get("cue_terms", ""))
    applies_when = normalize(meta.get("applies_when", ""))
    score = 0
    for signal in signals:
        expansions = [normalize(str(x)) for x in signal.get("expansions", [])]
        # A record must declare that a latent cue applies to it, or expose a
        # sufficiently specific expansion in its metadata/body. This prevents
        # generic emotions such as “失望” from loading the entire archive.
        declared = any(x and x in cue_terms for x in expansions) or any(x and x in applies_when for x in expansions)
        matched = sum(1 for x in expansions if x and x in searchable)
        if declared:
            score += 3
        score += min(matched, 2)
    return score


def snippet(body: str, limit: int = 360) -> str:
    text = " ".join(x.strip() for x in body.splitlines() if x.strip())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def load_records() -> list[dict[str, object]]:
    rows = []
    for path in sorted(RECORDS.glob("*.md")):
        meta, body = parse_frontmatter(path)
        rows.append({"path": path, "meta": meta, "body": body, "text": record_text(meta, body, path)})
    return rows


def load_branches() -> list[dict[str, object]]:
    rows = []
    for path in sorted(BRANCHES.glob("*.md")):
        if path.name == "index.md":
            continue
        meta, body = parse_frontmatter(path)
        rows.append({"path": path, "meta": meta, "body": body, "text": record_text(meta, body, path)})
    return rows


def short_record(row: dict[str, object], include_body: bool = True, match: str | None = None, signals: list[str] | None = None) -> dict[str, object]:
    meta = row["meta"]
    item = {
        "id": meta.get("id"),
        "kind": meta.get("kind"),
        "status": meta.get("status"),
        "confidence": meta.get("confidence"),
        "domain": meta.get("domain"),
        "valid_from": meta.get("valid_from"),
        "last_confirmed": meta.get("last_confirmed"),
        "source_refs": meta.get("source_refs"),
    }
    if match:
        item["match"] = match
    if signals:
        item["signals"] = signals
    if include_body:
        item["summary"] = snippet(row["body"])
    return {k: v for k, v in item.items() if v not in (None, "")}


def fit_budget(result: dict[str, object], budget: int, full_core_count: int, full_evidence_count: int) -> dict[str, object]:
    def encoded() -> str:
        return json.dumps(result, ensure_ascii=False, indent=2)

    # Preserve useful summaries by dropping low-priority evidence/core items first.
    for size in (240, 160, 100, 0):
        for collection in ("core", "evidence"):
            for item in result.get(collection, []):
                if size == 0:
                    item.pop("summary", None)
                else:
                    item["summary"] = snippet(item.get("summary", ""), size)
        while len(encoded()) > budget and result.get("evidence"):
            result["evidence"].pop()
        while len(encoded()) > budget and len(result.get("core", [])) > 1:
            result["core"].pop()
        if len(encoded()) <= budget:
            break

    result["omitted"] = {
        "core": max(0, full_core_count - len(result.get("core", []))),
        "evidence": max(0, full_evidence_count - len(result.get("evidence", []))),
    }
    # The omission metadata itself must also fit the advertised budget.
    while len(encoded()) > budget and result.get("evidence"):
        result["evidence"].pop()
        result["omitted"]["evidence"] += 1
    while len(encoded()) > budget and len(result.get("core", [])) > 1:
        result["core"].pop()
        result["omitted"]["core"] += 1
    if len(encoded()) > budget:
        result["note"] = "Budget too small for the minimum route and core metadata."
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query")
    ap.add_argument("--domain")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--as-of")
    ap.add_argument("--limit", type=int, default=12, help="maximum relevant core records; relevance, not token minimization, controls selection")
    ap.add_argument("--evidence-limit", type=int, default=8)
    ap.add_argument("--budget", type=int, default=12000, help="maximum JSON characters; default is intentionally generous")
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--legacy-proactive", action="store_true", help="enable the archived cue-term retriever for migration comparisons only")
    ap.add_argument("--no-proactive", action="store_true", help="deprecated compatibility alias; proactive retrieval is already disabled by default")
    ap.add_argument("--format", choices=["json", "markdown"], default="json")
    args = ap.parse_args()
    if args.budget < 600:
        raise SystemExit("--budget must be at least 600 characters")

    terms = query_terms(args.query)
    use_legacy_proactive = bool(args.legacy_proactive and not args.no_proactive)
    cue_rules = load_proactive_cues() if use_legacy_proactive else []
    signals = proactive_signals(args.query, cue_rules) if use_legacy_proactive else []
    proactive_terms = sorted({normalize(str(term)) for signal in signals for term in signal.get("expansions", []) if term})
    records = load_records()
    branches = load_branches()

    branch_hits = []
    for row in branches:
        meta = row["meta"]
        keywords = split_ids(meta.get("keywords", ""))
        text = row["text"]
        score = score_terms(terms, text, meta, args.query)
        if proactive_terms:
            score += min(3, sum(1 for term in proactive_terms if term in text))
        score += sum(2 for keyword in keywords if normalize(keyword) in normalize(args.query))
        if args.domain and meta.get("id") == args.domain:
            score += 100
        if score > 0:
            branch_hits.append((score, row))
    branch_hits.sort(key=lambda x: (-x[0], -int(x[1]["meta"].get("priority", "0") or 0), x[1]["meta"].get("id", "")))
    selected_branches = [row for _, row in branch_hits[:3]]
    selected_domains = {row["meta"].get("id") for row in selected_branches}
    if args.domain:
        selected_domains.add(args.domain)

    candidates = []
    for row in records:
        meta = row["meta"]
        status = meta.get("status")
        if not args.include_archived and status in {"archived", "deleted"}:
            continue
        if not args.as_of and status == "superseded":
            continue
        if not in_time(meta, args):
            continue
        direct_score = score_terms(terms, row["text"], meta, args.query)
        latent_score = 0 if args.no_proactive else score_proactive(signals, row)
        # A branch is a routing hint, not permission to load every record in it.
        # Explicit matches always qualify; latent matches need a declared cue
        # and a minimum score so a generic emotion cannot open the whole archive.
        if direct_score <= 0 and latent_score < 3:
            continue
        domain_bonus = 4 if meta.get("domain") in selected_domains else 0
        score = direct_score + latent_score + domain_bonus
        if direct_score > 0 and latent_score >= 3:
            match = "direct+proactive"
        elif direct_score > 0:
            match = "direct"
        else:
            match = "proactive"
        matched_signals = [str(signal.get("signal")) for signal in signals if latent_score and signal.get("signal")]
        candidates.append((score, row, match, matched_signals))
    # Explicit matches are always considered before latent matches; proactive
    # retrieval supplements a result rather than displacing a named concept.
    candidates.sort(key=lambda x: (0 if x[2] in {"direct", "direct+proactive"} else 1, -x[0], x[1]["meta"].get("status", ""), x[1]["meta"].get("id", "")))

    core = [(score, row, match, matched_signals) for score, row, match, matched_signals in candidates if row["meta"].get("kind") in CORE_KINDS][: max(args.limit, 0)]
    core_ids = {row["meta"].get("id") for _, row, _, _ in core}
    evidence_ids: list[str] = []
    for _, row, _, _ in core:
        meta = row["meta"]
        for field in ("supports",):
            for record_id in split_ids(meta.get(field, "")):
                if record_id not in evidence_ids and record_id not in core_ids:
                    evidence_ids.append(record_id)
    record_by_id = {row["meta"].get("id"): row for row in records}
    # Directly named events/entities/facts must be visible even when no model,
    # decision, or state happens to support them. Previously an exact lookup for
    # a person could score highly but disappear because entities only entered the
    # output as evidence attached to a selected core record.
    evidence = []
    direct_evidence_rows = [
        row for _, row, match, _ in candidates
        if row["meta"].get("kind") in EVIDENCE_KINDS and match in {"direct", "direct+proactive"}
    ]
    for row in direct_evidence_rows:
        record_id = row["meta"].get("id")
        if record_id not in {item["meta"].get("id") for item in evidence}:
            evidence.append(row)
        if len(evidence) >= max(args.evidence_limit, 0):
            break
    for record_id in evidence_ids:
        if len(evidence) >= max(args.evidence_limit, 0):
            break
        row = record_by_id.get(record_id)
        if not row or not in_time(row["meta"], args):
            continue
        if not args.include_archived and row["meta"].get("status") in {"archived", "deleted"}:
            continue
        if not args.as_of and row["meta"].get("status") == "superseded":
            continue
        if row["meta"].get("kind") in EVIDENCE_KINDS and row["meta"].get("id") not in {item["meta"].get("id") for item in evidence}:
            evidence.append(row)

    result = {
        "query": args.query,
        "retrieval_mode": "legacy-proactive" if use_legacy_proactive else "explicit-keyword-fallback",
        "route": [{"id": row["meta"].get("id"), "priority": row["meta"].get("priority")} for row in selected_branches],
        "time_filter": {"since": args.since, "until": args.until, "as_of": args.as_of},
        "core": [short_record(row, match=match, signals=matched_signals) for _, row, match, matched_signals in core],
        "evidence": [short_record(row) for row in evidence],
        "omitted": {"core": 0, "evidence": 0},
        "budget_chars": args.budget,
        "proactive": {
            "enabled": use_legacy_proactive,
            "signals": signals,
            "candidate_count": sum(1 for _, _, match, _ in candidates if "proactive" in match),
        },
    }
    result = fit_budget(result, args.budget, len(core), len(evidence))

    if args.format == "markdown":
        print(f"# Context Retrieval\n\nQuery: {args.query}\n")
        print("## Route")
        for branch in result["route"]:
            print(f"- `{branch['id']}`")
        for heading in ("core", "evidence"):
            print(f"\n## {'Core' if heading == 'core' else 'Evidence'}")
            for item in result[heading]:
                print(f"- `{item['id']}` [{item['kind']}, {item.get('status')}] {item.get('summary', '')}")
        print(f"\nOmitted: {result['omitted']}; budget={result['budget_chars']} characters")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

