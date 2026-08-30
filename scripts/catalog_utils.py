#!/usr/bin/env python3
"""Shared catalog helpers for the personal-understanding skill."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

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
    return [
        item.strip()
        for item in re.split(r"[;,]", value or "")
        if item.strip() and item.strip().lower() not in {"none", "null"}
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
        return snippet("; ".join(blocks), limit)
    selected = blocks[:2] + blocks[len(blocks) // 2 : len(blocks) // 2 + 1] + blocks[-2:]
    return snippet("; ".join(dict.fromkeys(selected)), limit)

def source_summary(path: Path) -> str:
    """Describe only the source itself, never a transitive record graph."""
    try:
        _, body = parse_frontmatter(path)
    except (UnicodeDecodeError, OSError):
        body = ""
    if body:
        return source_outline(path, body, 700)
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        return "Raw image source; the matching OCR or derived records may offer a topic summary, but exact content requires reading the image back."
    return f"Raw source: {path.name}. No sufficient derived summary yet; read the original back if needed."


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
    "survey": "Survey the v2 timeline spine, entity catalog, context cards, current state, follow-ups, and candidate hypotheses first; the legacy record catalog serves as a compatibility index.",
    "relevance_unit": "A unit of relevance is a context cluster, not a keyword or a single record: check topic, mood/energy, behavioral instances, current stressors, values and goals, changes over time, relationships/resources, and counterexamples separately.",
    "irrelevant": "Exclude only when no explainable connection remains after the global map and context expansion; sensitive does not mean irrelevant.",
    "possible": "Treat as a weak-relevance candidate: read derived summaries, relation paths, and time labels first, then decide whether to stop or escalate.",
    "medium": "Read direct records plus a limited cross-domain context cluster; seed IDs are not the boundary of relevance.",
    "high": "Read the derived summaries, and on demand the raw sources behind supports, contradicts, supersedes, counter-evidence, and time neighbors.",
    "expansion": "probe expands from an event to time neighbors, entities, places, objects, and context cards; deep reads only the selected fragments and preserves fidelity.",
    "review_trigger": "Failed verbatim captures, summary debt, misattributed people, time conflicts, due follow-ups, structural corruption, and imminent major decisions all enter v2 review.",
    "integration_question": "For every significant experience, judge whether it changed the user's values, boundaries, costs, expectations, counterexamples, or future choices — not just record the task outcome.",
    "cross_domain_frame": [
        "surface topic",
        "mood and energy",
        "behavior or self-assessment",
        "current stressors",
        "long-term values and goals",
        "changes over time",
        "counterexamples and competing explanations",
        "cross-domain corroboration",
    ],
}


def build_catalog_header() -> dict[str, Any]:
    """survey fast path: compute counts and the static policy only; no full record/source catalog (no hashing, no source matching)."""
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
                "boundary": "This is a derived summary and does not replace raw sources; person attribution, user corrections, and time status take priority over summary inference.",
            }
        )

    source_items: list[dict[str, Any]] = []
    for path in source_files():
        relative = path.relative_to(ROOT).as_posix()
        linked = linked_records(relative, records)
        kind = source_type(path)
        warnings: list[str] = []
        if kind in {"image", "ocr"}:
            warnings.append("OCR or image content may contain recognition errors; verify against the original image before exact quoting.")
        if kind == "external":
            warnings.append("Third-party or model analysis must not be taken directly as user facts or a stable personality model.")
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
        "note": "The global survey map provides only short derived summaries and relation hints, not raw source bodies; it is a global scan, not the final relevance ruling.",
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


def route_catalog(catalog: dict[str, Any], query: str = "", per_domain: int = 4) -> dict[str, Any]:
    """Return the global survey plus compatibility domain groupings.

    ``per_domain`` is retained for callers of the old API, but is no longer a
    hard cap: the model must see the complete current map before selecting a
    smaller probe set.
    """
    terms = query_terms(query)

    def score(item: dict[str, Any]) -> tuple[int, int, str]:
        searchable = " ".join(
            [item.get("id", ""), item.get("summary", ""), item.get("applies_when", "")]
            + item.get("aliases", [])
        ).casefold()
        direct = sum(1 for term in terms if term in searchable)
        current = 1 if item.get("status") == "current" else 0
        kind = 1 if item.get("kind") in ROUTING_KINDS else 0
        return (direct * 100 + current * 10 + kind, current, item.get("id", ""))

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
            "summary": "Current records, not yet classified, that may still influence personal decisions.",
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
        "routing_note": "This is the global survey view, not automatic retrieval results. The model browses the current map and the history index first, then picks records for probe/deep.",
    }


def write_catalog(catalog: dict[str, Any]) -> None:
    CATALOG_JSON.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Personal memory catalog",
        "",
        "Generated by `scripts/rebuild_views.py`; this file is a global survey and audit view — the source of truth remains the records and raw sources.",
        "",
        f"Catalog version: `{catalog['catalog_version']}`; {catalog['counts']['records']} records; {catalog['counts']['sources']} sources; {catalog['counts']['branches']} branches.",
        "",
        "## Derived records",
        "",
    ]
    for item in catalog["records"]:
        summary = item.get("summary", "").replace("\n", " ")
        lines.append(f"- `{item['id']}` [{item.get('kind')}, {item.get('status')}] {summary}")
    lines.extend(["", "## Raw source summaries", ""])
    for item in catalog["sources"]:
        warnings = "; ".join(item.get("warnings", []))
        suffix = f"; note: {warnings}" if warnings else ""
        lines.append(f"- `{item['path']}` [{item['source_type']}] {item['summary']}{suffix}")
    lines.extend(["", "## Usage boundaries", "", "survey first shows the current map and the history index; probe reads derived summaries; deep reads raw sources only for evidence verification.", ""])
    CATALOG_MD.write_text("\n".join(lines), encoding="utf-8")




