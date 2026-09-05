#!/usr/bin/env python3
"""Shared catalog helpers for the personal-understanding skill."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from storage import atomic_write_text
from typing import Any

import lexicon

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "memory" / "records"
BRANCHES = ROOT / "memory" / "branches"
SOURCES = ROOT / "sources"
CATALOG_JSON = ROOT / "memory" / "catalog.json"
CATALOG_MD = ROOT / "memory" / "catalog.md"
CATALOG_VERSION = "2.0.0"
SURVEY_SUMMARY_LIMIT = 120
HISTORY_SUMMARY_LIMIT = 96


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                body_start = index + 1
                break
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[body_start:]).strip()


def split_ids(value: str | None) -> list[str]:
    # LLM-written frontmatter sometimes uses JSON array form (["a", "b"]) instead
    # of the canonical a; b; c. Normalize it away instead of leaving bracket/quote
    # debris tokens that resolve to nothing and masquerade as dangling links.
    raw = (value or "").strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [
        item.strip().strip("'\"").strip()
        for item in re.split(r"[;,]", raw)
        if item.strip().strip("'\"").strip() and item.strip().strip("'\"").strip().lower() not in {"none", "null"}
    ]


def snippet(text: str, limit: int = 520) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def first_paragraph(text: str) -> str:
    paragraphs = [" ".join(block.split()) for block in re.split(r"\n\s*\n", text) if block.strip()]
    return paragraphs[0] if paragraphs else ""


def iso_date_from_name(name: str) -> str | None:
    match = re.search(r"(20\d{2})[-_.年](\d{1,2})[-_.月](\d{1,2})", name)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.search(r"(20\d{2})[-_.年](\d{1,2})", name)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-01"
    return None


def normalize_ref(value: str) -> str:
    return value.replace("\\", "/").strip().casefold()


def source_ref_matches(ref: str, relative_path: str) -> bool:
    ref_norm = normalize_ref(ref)
    path_norm = normalize_ref(relative_path)
    path_name = normalize_ref(Path(relative_path).name)
    path_stem = normalize_ref(Path(relative_path).stem)
    return ref_norm in {path_norm, path_name, path_stem} or ref_norm.endswith("/" + path_name)


def load_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(RECORDS.glob("*.md")):
        meta, body = parse_frontmatter(path)
        rows.append({"path": path, "meta": meta, "body": body})
    return rows


def load_branches() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(BRANCHES.glob("*.md")):
        if path.name == "index.md":
            continue
        meta, body = parse_frontmatter(path)
        rows.append({"path": path, "meta": meta, "body": body})
    return rows


def source_files() -> list[Path]:
    paths: list[Path] = []
    paths.extend(path for path in SOURCES.iterdir() if path.is_file())
    for folder in (SOURCES / "markdown", SOURCES / "external", SOURCES / "images", SOURCES / "ocr", SOURCES / "conversation"):
        if folder.exists():
            paths.extend(path for path in folder.rglob("*") if path.is_file() and not (folder.name == "conversation" and path.suffix.lower() == ".json"))
    return sorted(paths)


def source_type(path: Path) -> str:
    relative = path.relative_to(SOURCES).as_posix()
    if relative.startswith("conversation/"):
        return "conversation"
    if relative.startswith("external/"):
        return "external"
    if relative.startswith("images/"):
        return "image"
    if relative.startswith("ocr/"):
        return "ocr"
    return "markdown"


def expanded_source_refs(row: dict[str, Any], records_by_id: dict[str, dict[str, Any]], seen: set[str] | None = None) -> set[str]:
    seen = seen or set()
    record_id = row["meta"].get("id", "")
    if record_id in seen:
        return set()
    seen.add(record_id)
    refs = set(split_ids(row["meta"].get("source_refs")))
    for ref in list(refs):
        linked = records_by_id.get(ref)
        if linked:
            refs.update(expanded_source_refs(linked, records_by_id, seen))
    return refs


def linked_records(source_relative: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records_by_id = {row["meta"].get("id"): row for row in records if row["meta"].get("id")}
    relative = source_relative.replace("\\", "/")
    candidates = {relative}
    if relative.startswith("sources/ocr/"):
        candidates.add("sources/images/" + Path(relative).stem + ".jpg")
    if relative.startswith("sources/images/"):
        candidates.add("sources/ocr/" + Path(relative).stem + ".md")
    matches = []
    for row in records:
        refs = expanded_source_refs(row, records_by_id)
        if any(any(source_ref_matches(ref, candidate) for candidate in candidates) for ref in refs):
            matches.append(row)
    return matches



def source_outline(path: Path, body: str, limit: int = 900) -> str:
    """Build a bounded multi-position outline instead of trusting only the first paragraph."""
    if not body:
        return ""
    blocks = [" ".join(block.split()) for block in re.split(r"\n\s*\n", body) if block.strip()]
    if len(blocks) <= 4:
        return snippet("；".join(blocks), limit)
    selected = blocks[:2] + blocks[len(blocks) // 2 : len(blocks) // 2 + 1] + blocks[-2:]
    return snippet("；".join(dict.fromkeys(selected)), limit)

def source_summary(path: Path) -> str:
    """Describe only the source itself, never a transitive record graph."""
    try:
        _, body = parse_frontmatter(path)
    except (UnicodeDecodeError, OSError):
        body = ""
    if body:
        return source_outline(path, body, 700)
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        return "图片原始来源；对应 OCR 或派生记录可能提供主题摘要，精确内容需回读图片。"
    return f"原始来源：{path.name}。当前没有足够派生摘要，必要时需回读原文。"


RELATION_FIELDS = ("parent_ids", "related_ids", "supports", "contradicts", "supersedes")


def survey_record(item: dict[str, Any], summary_limit: int = SURVEY_SUMMARY_LIMIT) -> dict[str, Any]:
    """Return a compact, model-facing map entry without opening source bodies.

    The survey is a routing map only: relation paths and aliases live in the
    routing/full views and in probe expansion, not in the global survey.
    """
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "status": item.get("status"),
        "domain": item.get("domain") or "domain.unclassified",
        "confidence": item.get("confidence"),
        "summary": snippet(item.get("summary", ""), summary_limit),
        "raw_body_included": False,
    }


CATALOG_POLICY = {
    "raw_sources_are_immutable": True,
    "summary_is_not_authority": True,
    "current_conversation_has_priority": True,
    "legacy_proactive_cues_active": False,
    "global_survey_active": True,
    "v2_memory_spine_active": True,
    "verbatim_capture_required": True,
    "single_salience_axis": True,
    "adaptive_context_expansion": True,
    "catalog_reads_are_side_effect_free": True,
}

CATALOG_DECISION_CONTRACT = {
    "survey": "先扫描 v2 时间主干、实体目录、情境卡、当前状态、待回访和候选假设；旧记录目录作为兼容索引。",
    "relevance_unit": "相关性是一个上下文簇，不是一个关键词或单条记录：主题、情绪/能量、行为实例、当前压力、价值目标、时间变化、关系/资源和反例都要分别检查。",
    "irrelevant": "只有在全局地图和上下文扩展后都没有可解释连接，才排除；敏感不等于无关。",
    "possible": "进入弱相关候选，先读取派生摘要、关系路径和时间标签，再决定停止或升级。",
    "medium": "读取直接记录及有限跨域上下文簇；种子 ID 不是相关性边界。",
    "high": "读取派生概括，并按需读取 supports、contradicts、supersedes、反向证据和时间邻居的原始来源。",
    "expansion": "probe 从事件发散到时间邻居、实体、地点、对象和情境卡；deep 只读取选中 fragment，并保留 fidelity。",
    "review_trigger": "原话捕获失败、摘要债务、人物归属错误、时间冲突、待回访到期、结构损坏和临近重要决策进入 v2 审查。",
    "integration_question": "每次重要经历都要判断它是否改变了用户的价值、边界、代价、期待、反例或未来选择，而不只记录任务结果。",
    "cross_domain_frame": [
        "表面主题",
        "情绪和能量",
        "行为或自我评价",
        "当前压力源",
        "长期价值与目的",
        "时间变化",
        "反例与竞争解释",
        "跨领域交叉印证",
    ],
}


def build_catalog_header() -> dict[str, Any]:
    """survey 快速路径：只算计数和静态政策，不构建记录/来源全目录（无哈希、无来源匹配）。"""
    metas: list[dict[str, str]] = []
    for path in RECORDS.glob("*.md"):
        try:
            meta, _ = parse_frontmatter(path)
        except (OSError, UnicodeDecodeError):
            continue
        metas.append(meta)
    branches = [path for path in BRANCHES.glob("*.md") if path.name != "index.md"]
    current = sum(1 for meta in metas if meta.get("status") == "current")
    return {
        "catalog_version": CATALOG_VERSION,
        "generated_at": date.today().isoformat(),
        "policy": CATALOG_POLICY,
        "decision_contract": CATALOG_DECISION_CONTRACT,
        "counts": {"records": len(metas), "sources": len(source_files()), "branches": len(branches)},
        "survey": {"counts": {"current": current, "history": len(metas) - current}},
    }


def build_catalog() -> dict[str, Any]:
    records = load_records()
    record_items: list[dict[str, Any]] = []
    for row in records:
        meta = row["meta"]
        record_items.append(
            {
                "id": meta.get("id"),
                "kind": meta.get("kind"),
                "status": meta.get("status"),
                "confidence": meta.get("confidence"),
                "sensitivity": meta.get("sensitivity"),
                "record_role": meta.get("record_role") or "personal_memory",
                "display_label": meta.get("display_label", ""),
                "domain": meta.get("domain"),
                "valid_from": meta.get("valid_from"),
                "valid_until": meta.get("valid_until"),
                "last_confirmed": meta.get("last_confirmed"),
                "aliases": split_ids(meta.get("aliases")),
                "applies_when": meta.get("applies_when", ""),
                "parent_ids": split_ids(meta.get("parent_ids")),
                "related_ids": split_ids(meta.get("related_ids")),
                "supports": split_ids(meta.get("supports")),
                "contradicts": split_ids(meta.get("contradicts")),
                "supersedes": split_ids(meta.get("supersedes")),
                "source_refs": split_ids(meta.get("source_refs")),
                "summary": snippet(row["body"], 560),
                "boundary": "这是派生概括，不替代原始来源；人物归属、用户纠正和时间状态优先于摘要推断。",
            }
        )

    source_items: list[dict[str, Any]] = []
    for path in source_files():
        relative = path.relative_to(ROOT).as_posix()
        linked = linked_records(relative, records)
        kind = source_type(path)
        warnings: list[str] = []
        if kind in {"image", "ocr"}:
            warnings.append("OCR 或图片内容可能存在识别误差；精确引用前必须核对原图。")
        if kind == "external":
            warnings.append("第三方或模型分析不能直接当作用户事实或稳定人格模型。")
        ocr_path = None
        if kind == "image":
            candidate = SOURCES / "ocr" / f"{path.stem}.md"
            if candidate.exists():
                ocr_path = candidate.relative_to(ROOT).as_posix()
        raw_bytes = path.read_bytes()
        linked_ids = [row["meta"].get("id") for row in linked if row["meta"].get("id")]
        summary = source_summary(path)
        source_items.append(
            {
                "id": "source." + re.sub(r"[^a-z0-9._-]+", "-", relative.casefold()).strip("-"),
                "path": relative,
                "read_path": relative,
                "source_type": kind,
                "title": path.stem,
                "date": iso_date_from_name(path.name),
                "summary": summary,
                "outline": summary,
                "summary_basis": "source-outline-only",
                "record_refs": linked_ids,
                "topics": sorted({row["meta"].get("domain") for row in linked if row["meta"].get("domain")}),
                "warnings": warnings,
                "ocr_path": ocr_path,
                "byte_size": len(raw_bytes),
                "content_hash": hashlib.sha256(raw_bytes).hexdigest(),
                "review_required": not linked_ids or len(raw_bytes) > 50000 or bool(warnings),
                "raw_body_included": False,
            }
        )

    branch_items = []
    for row in load_branches():
        meta = row["meta"]
        branch_items.append(
            {
                "id": meta.get("id"),
                "priority": meta.get("priority"),
                "summary": snippet(first_paragraph(row["body"]), 360),
                "record_refs": split_ids(meta.get("record_refs")),
            }
        )

    catalog = {
        "catalog_version": CATALOG_VERSION,
        "generated_at": date.today().isoformat(),
        "policy": CATALOG_POLICY,
        "decision_contract": CATALOG_DECISION_CONTRACT,
        "counts": {
            "records": len(record_items),
            "sources": len(source_items),
            "branches": len(branch_items),
        },
        "branches": branch_items,
        "records": record_items,
        "sources": source_items,
    }

    current = [item for item in record_items if item.get("status") == "current"]
    history = [item for item in record_items if item.get("status") != "current"]
    catalog["survey"] = {
        "version": CATALOG_VERSION,
        "current": [survey_record(item) for item in current],
        "history": [survey_record(item, HISTORY_SUMMARY_LIMIT) for item in history],
        "counts": {"current": len(current), "history": len(history)},
        "note": "全局勘察地图只提供派生短摘要和关系提示，不包含原始来源正文；它是全局扫描，不是最终相关性裁决。",
    }
    return catalog


ROUTING_KINDS = {"state", "decision", "model", "value", "heuristic", "rule", "preference"}


def query_terms(query: str) -> list[str]:
    """Tokenize mixed Chinese/Latin queries without requiring a segmentation package."""
    compact = query.casefold()
    terms: list[str] = []
    terms.extend(re.findall(r"[a-z0-9_]+", compact))
    for run in re.findall(r"[\u4e00-\u9fff]+", compact):
        if len(run) <= 4:
            terms.append(run)
        terms.extend(run[index : index + size] for size in (2, 3, 4) for index in range(len(run) - size + 1))
        terms.extend(char for char in run if char.strip())
    return list(dict.fromkeys(term for term in terms if term))


def weighted_query_terms(query: str) -> list[str]:
    """Tokenize for weighted ranking: same n-gram coverage as query_terms but without
    single-character noise from CJK runs longer than one char.

    Single chars match 60%+ of all records (在/一/人/看…), which lets long records
    pile up cheap hits and bury rare decisive terms (只狼/弦一郎/猫学派). A single-char
    term is only kept when the query itself is that one char.

    2.6.0: mixed CJK/Latin proper nouns are glued as extra terms (巫师3, 晕3D — the
    CJK/ASCII boundary otherwise splits the sharpest anchor a query carries), and
    the slice list is cleaned by the lexicon (resources/lexicon: vendored jieba
    dict + archive self-trained proper nouns). The lexicon only deletes OOV
    cross-word slices and stray ASCII single chars; when nothing content-bearing
    survives it falls back to the unfiltered list, so it can never blind recall.
    """
    compact = query.casefold()
    terms: list[str] = []
    terms.extend(re.findall(r"[a-z0-9_]+", compact))
    for run in re.findall(r"[\u4e00-\u9fff]+", compact):
        if len(run) <= 4:
            terms.append(run)
        terms.extend(run[index : index + size] for size in (2, 3, 4) for index in range(len(run) - size + 1))
        if len(run) == 1:
            terms.append(run)
    terms.extend(lexicon.mixed_run_terms(query))
    terms = list(dict.fromkeys(term for term in terms if term))
    kept, _dropped = lexicon.filter_query_terms(terms)
    return kept


def single_char_aliases(rows: list[dict]) -> set[str]:
    """Curated single-character entity aliases (妈/爸/哥…). These are referential,
    not noise: the ×0.15 single-char demotion is meant for chars like 在/一/人 that
    match 60%+ of records, but a family word the user actually types to mean a person
    must keep its weight, or the entity→event feedback cannot carry it."""
    out: set[str] = set()
    for row in rows:
        for alias in row.get("aliases") or []:
            alias = str(alias).strip()
            if len(alias) == 1 and not alias.isascii():
                out.add(alias)
    return out


# Closed-class Chinese function words: interrogatives, copulas, particles. They are
# referentially empty for archive recall, yet a word like 怎么 can be RARE in a given
# archive (few records quote a "how to" question), so IDF mistakes it for a distinctive
# term and pulls in every record that happens to contain it — the one survivor of the
# §4.1 single-char flood (T02: family/health events surfaced for a 只狼 strategy query,
# each matched only on 怎么). Demote to noise AND never let one qualify a record for a
# retrieval slot — the single exception to "2-char ⇒ content". Additions must stay
# closed-class; never put open domain nouns here.
STOP_TERMS = frozenset({
    "怎么", "怎样", "咋样", "咋", "如何", "什么", "啥", "为啥", "为何", "为什么",
    "哪个", "哪些", "哪里", "谁", "是否", "呢", "吗", "吧", "啊",
})


def content_terms(terms: list[str], alias_singles: set[str]) -> set[str]:
    """Terms that carry real signal: Latin tokens, multi-char CJK, or a single char
    that is a curated entity alias. A record whose only hits are outside this set
    matched pure noise (a stray 防/钱/在) or a closed-class function word (怎么) and
    must not consume a retrieval slot.

    2.6.0: a lone ASCII char ("3" out of 巫师3) is not signal either — inside
    record ids and dates (20260830) it matches nearly every row and was the #1
    junk qualifier measured on 2026-09-05. It qualifies only when it is the
    entire query (a bare "3" is the user's whole intent, unlikely but legal)."""
    core = {t for t in terms if t not in STOP_TERMS and ((t.isascii() and len(t) >= 2) or len(t) >= 2 or t in alias_singles)}
    if len(terms) == 1 and terms[0].isascii():
        core = set(terms)
    return core


def term_weights(terms: list[str], docs: list[str], alias_singles: set[str] = frozenset()) -> dict[str, float]:
    """IDF-style weights over a corpus of searchable texts.

    Rare terms weigh more; Latin tokens and multi-char CJK terms get a bonus, single
    CJK chars are demoted to near-noise. Corpus-wide document frequency is what
    stops common chars from outranking distinctive proper nouns. A single char that
    is a curated entity alias (see single_char_aliases) is referential, not noise, and
    keeps the multi-char bonus so 妈/爸 queries can reach the family cluster. Closed-class
    function words (STOP_TERMS) are demoted like noise even when rare — IDF alone cannot
    tell a rare proper noun from a rare 怎么.

    2.6.0: lexicon-OOV CJK slices (neither the vendored jieba dict nor the
    self-trained archive lexicon knows them — cross-word accidents like 郎我/段那)
    are capped at ×0.4. They keep recall — a sole hit still wins a relative
    ranking — but can no longer out-anchor dictionary-known decisive terms, which
    is what let sentence-form queries push unrelated long records forward.
    """
    total = max(len(docs), 1)
    weights: dict[str, float] = {}
    for term in terms:
        if not term:
            continue
        df = sum(1 for doc in docs if term in doc)
        weight = math.log(1 + total / max(df, 1))
        if term in STOP_TERMS:
            weight *= 0.15
        elif term.isascii():
            weight *= 1.6
        elif len(term) >= 2 or term in alias_singles:
            weight *= 1.3
        else:
            weight *= 0.15
        if len(term) >= 2 and not term.isascii() and not lexicon.known(term) and not lexicon.is_mixed(term):
            weight *= 0.4
        weights[term] = weight
    return weights


def weighted_match_score(haystack: str, weights: dict[str, float]) -> float:
    """Length-normalized weighted term match.

    Sum of weights for terms present in the haystack, divided by 1+log(len) so very
    long records cannot win on bulk alone. A 5000-char record needs far more matched
    terms than a 200-char one to reach the same score.
    """
    text = haystack.casefold()
    if not weights or not text:
        return 0.0
    total = sum(weight for term, weight in weights.items() if term in text)
    return total / (1 + math.log(1 + len(text)))


# Causal hypotheses are explanations, not facts (causal-hypothesis policy / SKILL.md:
# 因果假设只有在当前问题需要解释时才进入深读；普通事实问题不自动加载它). Carrying every
# claim into every read both inflates context and smuggles candidate causes in as if
# they were established record content. The gate below is retrieval-layer engineering,
# not a model-behavior rule: a hypothesis travels only when the query's signal-bearing
# terms actually hit its text; otherwise the catalog shows a claim-less stub so the
# model still knows the hypothesis exists and can reach for it deliberately.
CONFIDENCE_RANK = {"very-high": 0, "high": 1, "medium-high": 2, "medium": 3, "low-medium": 4, "low": 5}


def hypothesis_haystack(row: dict) -> str:
    values = [str(row.get(key, "")) for key in ("id", "claim", "scope", "mechanism")]
    values += [str(item) for item in (row.get("alternatives") or [])]
    values += [str(item) for item in (row.get("supports") or [])]
    return " ".join(values).casefold()


def select_hypotheses(rows: list[dict], terms: list[str], content: set[str], weights: dict[str, float] | None = None, cap: int = 6) -> list[dict]:
    """Hypotheses the current query is allowed to see (gate rationale above).

    A hypothesis qualifies only on a content-term hit (STOP_TERMS and stray single
    chars cannot qualify it, same rule as retrieval slots). Ranked by hit weight —
    raw hit count when no IDF weights are supplied — then confidence, then id.
    No query, or a query with no content terms → empty: existence stays visible via
    the catalog's claim-less stubs, content never loads itself.
    """
    if not terms or not content:
        return []
    scored = []
    for row in rows:
        text = hypothesis_haystack(row)
        hits = [term for term in content if term in text]
        if not hits:
            continue
        score = sum(weights.get(term, 0.0) for term in hits) if weights else float(len(hits))
        scored.append((score, CONFIDENCE_RANK.get(str(row.get("confidence") or "").casefold(), 3), str(row.get("id", "")), row))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [row for _, _, _, row in scored[:cap]]


def anchor_ratio(text: str, weights: dict[str, float], content: set[str], max_query_weight: float) -> float:
    """Anchor demotion for sentence-form queries (acceptance-round finding).

    Keyword queries name their target (只狼), so any hit is meaningful. A full
    sentence, though, carries dozens of incidental content bigrams (小时/阶段/那个),
    and a LONG record matching a handful of those can outscore the record that
    matches the query's rare decisive term — the T02/T13 timeline floods were built
    from exactly such records (the #1 junk row matched only 小时+阶段 out of 62
    content terms). Demote each row by the strength of its BEST matched term
    relative to the query's best term: a record whose strongest hit is a common
    bigram cannot outrank one that hit the anchor word. Self-normalizing: when the
    query has no rare term at all, every ratio approaches 1 and ranking degrades to
    the previous behavior. Rows with NO content-term hit keep ratio 1 — they are
    already gated out of slots elsewhere, and entity-feedback-boosted rows must not
    be double-punished for their own text.
    """
    if not content or max_query_weight <= 0:
        return 1.0
    best = 0.0
    for term in content:
        if term in text:
            weight = weights.get(term, 0.0)
            if weight > best:
                best = weight
    return best / max_query_weight if best else 1.0


RECENCY_HALF_LIFE_DAYS = 180

def recency_factor(row: dict, today: date | None = None, half_life: int = RECENCY_HALF_LIFE_DAYS) -> float:
    """Generative-Agents-style time relevance for the lexical channel (2.6.1 §4c,
    measured): multiplicative 0.5^(age/half_life) on event_value. On an auto-derived
    31-case time-consistency gold set (same entity carries an old and a newer record,
    "X最近的情况" queries) it halves the old-beats-new violation rate 0.419→0.161
    while a 314-case precise-recall net stays flat (0.617→0.617) and the associative
    golden regressions (h16 房子, 推荐游戏→晕3D) pass unchanged.

    Two measured design rules, both born from regressions:
    - UNDATED records are NEUTRAL (factor 1.0), never treated as ancient: 9% of
      events lack date_start and treating them as old silently buried correctly
      titled records (SET-A regression).
    - half_life 90..730 days were swept — violation rate is insensitive beyond
      90, so the exact constant is not a tuning surface; 180 sits mid-range.
    The knowledge channel keeps NO recency factor: cards are living summaries
    re-confirmed over time (last_confirmed drifts with updates), and the
    associative channel has its own date tiebreak inside records_of.
    """
    ds = str(row.get("date_start") or "")[:10]
    if len(ds) != 10:
        return 1.0
    try:
        y, m, d = int(ds[:4]), int(ds[5:7]), int(ds[8:10])
    except ValueError:
        return 1.0
    try:
        age = max(0, ((today or date.today()) - date(y, m, d)).days)
    except ValueError:
        return 1.0
    return 0.5 ** (age / half_life)


def route_catalog(catalog: dict[str, Any], query: str = "", per_domain: int = 4) -> dict[str, Any]:
    """Return the global survey plus compatibility domain groupings.

    ``per_domain`` is retained for callers of the old API, but is no longer a
    hard cap: the model must see the complete current map before selecting a
    smaller probe set.
    """
    terms = weighted_query_terms(query)

    def searchable(item: dict[str, Any]) -> str:
        return " ".join(
            [item.get("id", ""), item.get("summary", ""), item.get("applies_when", "")]
            + item.get("aliases", [])
        ).casefold()

    # Same weighted ranking as probe: IDF over current records so rare terms
    # (只狼/猫学派) outrank common chars, and long summaries stop dominating.
    # The anchor demotion (below) applies here too: dedup queries are verbatim
    # user sentences, and a record matching only common sentence bigrams must
    # not outrank the one that hit the query's rare term.
    content = content_terms(terms, frozenset())
    corpus = [searchable(item) for item in catalog["records"]]
    weights = term_weights(terms, corpus)
    max_query_weight = max((weights.get(term, 0.0) for term in content), default=0.0)

    def score(item: dict[str, Any]) -> tuple[float, float, int, str]:
        text = searchable(item)
        direct = weighted_match_score(text, weights) * anchor_ratio(text, weights, content, max_query_weight)
        current = 1 if item.get("status") == "current" else 0
        kind = 1 if item.get("kind") in ROUTING_KINDS else 0
        return (direct * 100 + current * 10 + kind, direct, current, item.get("id", ""))

    selected = [item for item in catalog["records"] if item.get("status") == "current"]
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        domain = item.get("domain") or "domain.unclassified"
        by_domain.setdefault(domain, []).append(item)

    domains = []
    for branch in catalog["branches"]:
        domain_id = branch["id"]
        candidates = sorted(by_domain.pop(domain_id, []), key=score, reverse=True)
        domains.append({
            "id": domain_id,
            "summary": branch["summary"],
            "records": [{**item, "summary": snippet(item.get("summary", ""), SURVEY_SUMMARY_LIMIT)} for item in candidates],
        })
    if by_domain:
        domains.append({
            "id": "domain.unclassified",
            "summary": "未归类但可影响个人决策的当前记录。",
            "records": [{**item, "summary": snippet(item.get("summary", ""), SURVEY_SUMMARY_LIMIT)} for item in sorted((item for rows in by_domain.values() for item in rows), key=score, reverse=True)],
        })

    return {
        "catalog_version": CATALOG_VERSION,
        "view": "routing",
        "query": query,
        "policy": catalog["policy"],
        "decision_contract": catalog["decision_contract"],
        "counts": catalog["counts"],
        "survey": catalog.get("survey", {}),
        "domains": domains,
        "routing_note": "这是全局勘察视图，不是自动检索结果。模型先浏览当前地图和历史索引，再选择 probe/deep 记录。",
    }


def write_catalog(catalog: dict[str, Any]) -> None:
    atomic_write_text(CATALOG_JSON, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# 个人资料目录",
        "",
        "由 `scripts/rebuild_views.py` 生成；本文件是全局勘察与审计视图，事实来源仍回到记录和原文。",
        "",
        f"目录版本：`{catalog['catalog_version']}`；记录 {catalog['counts']['records']} 条；来源 {catalog['counts']['sources']} 个；分支 {catalog['counts']['branches']} 个。",
        "",
        "## 派生记录",
        "",
    ]
    for item in catalog["records"]:
        summary = item.get("summary", "").replace("\n", " ")
        lines.append(f"- `{item['id']}` [{item.get('kind')}, {item.get('status')}] {summary}")
    lines.extend(["", "## 原始来源级摘要", ""])
    for item in catalog["sources"]:
        warnings = "；".join(item.get("warnings", []))
        suffix = f"；注意：{warnings}" if warnings else ""
        lines.append(f"- `{item['path']}` [{item['source_type']}] {item['summary']}{suffix}")
    lines.extend(["", "## 使用边界", "", "survey 先展示当前地图和历史索引；probe 读取派生概括；deep 仅在证据核验时回读原始来源。", ""])
    atomic_write_text(CATALOG_MD, "\n".join(lines))




