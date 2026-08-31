#!/usr/bin/env python3
"""Build and audit the v2 memory-shaped archive."""
from __future__ import annotations
import hashlib, json, os, re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from catalog_utils import ROOT, load_records, load_branches, split_ids
from derivation_ledger import discover_captures
from storage import atomic_write_text, mutation_lock

V2_ROOT = ROOT / "memory" / "v2"
PAGES_ROOT = V2_ROOT / "pages"
ENTITY_PAGES = PAGES_ROOT / "entities"
EVENT_PAGES = PAGES_ROOT / "events"
CONVERSATION_ROOT = ROOT / "sources" / "conversation"
IMAGES_ROOT = ROOT / "sources" / "images"
V2_VERSION = "2.0.0"
JSONL_FILES = {
    "fragments": V2_ROOT / "fragments.jsonl",
    "events": V2_ROOT / "timeline.jsonl",
    "entities": V2_ROOT / "entities.jsonl",
    "contexts": V2_ROOT / "contexts.jsonl",
    "followups": V2_ROOT / "followups.jsonl",
    "hypotheses": V2_ROOT / "hypotheses.jsonl",
    "relations": V2_ROOT / "relations.jsonl",
    "knowledge": V2_ROOT / "knowledge.jsonl",
}
SALIENCE_LABELS = {3: "主轴", 2: "关键", 1: "关联", 0: "提及"}
FOLLOWUP_OPEN_STATUSES = {"pending", "due", "overdue"}
ENTITY_REDIRECTS = {
    "entity.friend.best-friend": "entity.friend.xiaopang",
    "entity.friend.xiaoze": "entity.friend.xiaozhang",
    "entity.relationship.ambiguous-person": "entity.relationship.xiaoxu",
}


def canonical_entity_id(entity_id: str) -> str:
    seen = set()
    while entity_id in ENTITY_REDIRECTS and entity_id not in seen:
        seen.add(entity_id)
        entity_id = ENTITY_REDIRECTS[entity_id]
    return entity_id


def slug(value: str, fallback: str = "item") -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value.casefold()).strip("-") or fallback


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_text_atomic(path: Path, content: str) -> None:
    """Unique-temp atomic write; callers hold the shared rebuild lock."""
    atomic_write_text(path, content)


def followup_open(row: dict[str, Any]) -> bool:
    return row.get("status", "pending") in FOLLOWUP_OPEN_STATUSES


def followup_due_day(row: dict[str, Any]) -> str | None:
    value = str(row.get("due_at") or "").strip()
    return value[:10] if value else None


def followup_is_due(row: dict[str, Any], today: str | None = None) -> bool:
    """全库唯一的"已到期"判定：日期截断到天，避免带时间部分的 due_at 永不命中。"""
    day = followup_due_day(row)
    return bool(followup_open(row) and day and day <= (today or date.today().isoformat()))


def jsonl_read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"_parse_error": lineno, "_raw": line})
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def jsonl_write(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    ordered = sorted(rows, key=lambda row: str(row.get("id", "")))
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ordered)
    write_text_atomic(path, payload)


def clean_text(value: str) -> str:
    return " ".join(value.split())


def parse_date_value(value: str | None) -> tuple[str | None, str]:
    raw = str(value or "").strip()
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", raw):
        return raw, "day"
    if re.fullmatch(r"20\d{2}-\d{2}", raw):
        return raw + "-01", "month"
    if re.fullmatch(r"20\d{2}", raw):
        return raw + "-01-01", "year"
    return None, "unknown"


def date_from_id(record_id: str) -> tuple[str | None, str]:
    match = re.search(r"(20\d{2})[-_.](\d{1,2})[-_.](\d{1,2})", record_id)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}", "id-derived"
    match = re.search(r"(20\d{2})[-_.](\d{1,2})", record_id)
    if match:
        y, m = match.groups()
        return f"{int(y):04d}-{int(m):02d}-01", "id-derived-month"
    return None, "unknown"


def date_info(meta: dict[str, str]) -> dict[str, Any]:
    for field, basis in (("valid_from", "record-valid-from"), ("last_confirmed", "record-confirmed")):
        parsed, precision = parse_date_value(meta.get(field))
        if parsed:
            explicit_end, _ = parse_date_value(meta.get("date_end"))
            return {"date_start": parsed, "date_end": meta.get("valid_until") or explicit_end or parsed, "date_precision": meta.get("date_precision") or precision, "date_basis": meta.get("date_basis") or basis, "date_text": meta.get(field)}
    parsed, precision = date_from_id(meta.get("id", ""))
    if parsed:
        explicit_end, _ = parse_date_value(meta.get("date_end"))
        return {"date_start": parsed, "date_end": explicit_end or parsed, "date_precision": precision, "date_basis": "id-derived", "date_text": parsed}
    return {"date_start": None, "date_end": None, "date_precision": "unknown", "date_basis": "undated", "date_text": "未标日期"}


def salience_for(meta: dict[str, str], body: str) -> tuple[int, str]:
    raw = meta.get("salience") or meta.get("memory_weight") or ""
    try:
        return max(0, min(3, int(raw))), "explicit"
    except (TypeError, ValueError):
        pass
    kind = meta.get("kind", "")
    record_id = meta.get("id", "")
    relation_count = sum(len(split_ids(meta.get(field))) for field in ("supports", "contradicts", "supersedes", "related_ids"))
    if kind in {"decision", "state"}:
        return 2, "imported-kind-heuristic"
    if kind in {"model", "value"}:
        return 3, "imported-kind-heuristic"
    if "correction" in record_id or relation_count >= 4 or len(body) >= 700:
        return 2, "imported-impact-heuristic"
    if kind in {"event", "fact", "preference", "rule", "heuristic", "entity"}:
        return 1, "imported-kind-heuristic"
    return 0, "imported-default"


def record_title(meta: dict[str, str], body: str) -> str:
    aliases = split_ids(meta.get("aliases"))
    if aliases:
        return aliases[0]
    text = clean_text(body)
    sentence = re.split(r"[。！？.!?]", text, maxsplit=1)[0].strip()
    return (sentence[:40] + "…") if len(sentence) > 40 else (sentence or meta.get("id", "未命名"))


def capture_records() -> list[dict[str, Any]]:
    captures = []
    if not CONVERSATION_ROOT.exists():
        return captures
    for file in sorted(CONVERSATION_ROOT.glob("*.txt")):
        text = file.read_text(encoding="utf-8")
        meta_file = file.with_suffix(".json")
        meta: dict[str, Any] = {}
        if meta_file.exists():
            try:
                value = json.loads(meta_file.read_text(encoding="utf-8"))
                if isinstance(value, dict): meta = value
            except json.JSONDecodeError:
                meta = {"metadata_error": True}
        captures.append({"capture_id": meta.get("capture_id") or file.stem, "path": file.relative_to(ROOT).as_posix(), "text": text, "sha256": sha256_text(text), "captured_at": meta.get("captured_at") or datetime.fromtimestamp(file.stat().st_mtime).isoformat(timespec="seconds"), "speaker": meta.get("speaker", "user"), "message_kind": meta.get("message_kind", "personal-understanding-update"), "capture_kind": "text"})
    attachment_meta_files = set(CONVERSATION_ROOT.glob("*.attachment.json"))
    if IMAGES_ROOT.exists():
        attachment_meta_files.update(IMAGES_ROOT.glob("*.json"))
    for meta_file in sorted(attachment_meta_files):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(meta, dict) or not meta.get("capture_id") or not meta.get("source_path"):
            continue
        capture_id = meta.get("capture_id") or meta_file.name.removesuffix(".attachment.json")
        source_path = str(meta.get("source_path") or "")
        content_type = meta.get("content_type") or ("image/jpeg" if Path(source_path).suffix.casefold() in {".jpg", ".jpeg"} else "application/octet-stream")
        descriptor = f"[原始附件：{meta.get('original_filename') or Path(source_path).name}；类型：{content_type}；SHA256：{meta.get('sha256') or ''}]"
        captures.append({"capture_id": capture_id, "path": source_path, "metadata_path": meta_file.relative_to(ROOT).as_posix(), "text": descriptor, "sha256": meta.get("sha256"), "captured_at": meta.get("captured_at"), "speaker": meta.get("speaker", "user"), "message_kind": meta.get("message_kind", "attachment"), "capture_kind": "attachment", "content_type": content_type, "byte_length": meta.get("byte_length")})
    return captures


def capture_fragment_parity_errors(fragment_ids: Iterable[str], root: Path = ROOT) -> list[dict[str, Any]]:
    """Audit v2 capture fragments against the independent capture registry scanner."""
    discovered_capture_ids = set(discover_captures(root))
    fragment_capture_ids = {
        str(fragment_id).removeprefix("fragment.capture.")
        for fragment_id in fragment_ids
        if str(fragment_id).startswith("fragment.capture.")
    }
    errors: list[dict[str, Any]] = []
    for capture_id in sorted(discovered_capture_ids - fragment_capture_ids):
        errors.append({"code": "capture-fragment-missing", "capture_id": capture_id})
    for capture_id in sorted(fragment_capture_ids - discovered_capture_ids):
        errors.append({"code": "capture-fragment-without-source", "capture_id": capture_id})
    return errors


def make_fragment(fragment_id: str, text: str, source_refs: list[str], source_kind: str, fidelity: str, **extra: Any) -> dict[str, Any]:
    return {"id": fragment_id, "verbatim": text, "verbatim_sha256": sha256_text(text), "source_refs": source_refs, "source_kind": source_kind, "fidelity": fidelity, "authoritative": False, "speaker": "unknown", "fragment_type": "context", "record_refs": [], "entity_refs": [], "locator": {}, "note": "", **extra}


def build_fragments(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    fragments: list[dict[str, Any]] = []
    record_fragments: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        meta, body = row["meta"], row["body"]
        record_id = meta.get("id")
        if not record_id or not body:
            continue
        fid = f"fragment.legacy.{slug(record_id)}"
        fragments.append(make_fragment(fid, body, split_ids(meta.get("source_refs")), "legacy-derived-record", "summary_only", record_refs=[record_id], fragment_type="legacy-summary", note="旧版派生记录；不能当作用户原话。"))
        record_fragments[record_id].append(fid)
    capture_map: dict[str, str] = {}
    fragment_by_id: dict[str, dict[str, Any]] = {}
    for capture in capture_records():
        fid = f"fragment.capture.{slug(capture['capture_id'])}"
        capture_map[capture["capture_id"]] = fid
        is_attachment = capture.get("capture_kind") == "attachment"
        fragment = make_fragment(fid, capture["text"], [capture["path"]], "conversation-capture", "exact_attachment" if is_attachment else "verbatim", speaker=capture["speaker"], fragment_type="raw-attachment" if is_attachment else "raw-message", locator={"capture_id": capture["capture_id"], "path": capture["path"], "metadata_path": capture.get("metadata_path")}, authoritative=capture["speaker"] == "user", note="不可变原始附件；可读文本需使用明确链接的 OCR/转写派生。" if is_attachment else "不可变会话原文。", attachment_sha256=capture.get("sha256") if is_attachment else None, content_type=capture.get("content_type") if is_attachment else None, byte_length=capture.get("byte_length") if is_attachment else None)
        fragments.append(fragment); fragment_by_id[fid] = fragment
    for row in rows:
        meta = row["meta"]; record_id = meta.get("id")
        if not record_id: continue
        refs = split_ids(meta.get("verbatim_refs"))
        refs += [Path(ref).stem for ref in split_ids(meta.get("source_refs")) if ref.startswith("sources/conversation/")]
        for ref in refs:
            key = ref.replace("fragment.capture.", "")
            if key in capture_map and capture_map[key] not in record_fragments[record_id]:
                record_fragments[record_id].append(capture_map[key])
                if record_id not in fragment_by_id[capture_map[key]]["record_refs"]:
                    fragment_by_id[capture_map[key]]["record_refs"].append(record_id)
    return fragments, dict(record_fragments)

SEED_ENTITIES = [
    ("entity.school.guangxi-minzu-university", "广西民族大学", "school_or_organization", ["广西民族大学"]),
    ("entity.program.archives-science", "档案学", "concept", ["档案学"]),
    ("entity.concept.archaeology", "考古", "concept", ["考古", "田野考古"]),
    ("entity.interest.football", "足球", "game_or_media", ["足球", "踢球"]),
    ("entity.school.high-school", "高中", "school_or_organization", ["高中", "高三", "文科班"]),
    ("entity.school.middle-school", "初中", "school_or_organization", ["初中"]),
    ("entity.object.laptop", "电脑与笔记本", "object", ["电脑", "笔记本", "笔记本电脑"]),
    ("entity.object.football-shoes", "足球鞋", "object", ["足球鞋", "碎钉"]),
    ("entity.object.earbuds", "耳机与平头塞", "object", ["耳机", "平头塞"]),
    ("entity.book.tianchao-collapse", "《天朝的崩溃》", "book_or_work", ["天朝的崩溃"]),
    ("entity.book.century-solitude", "《百年孤独》", "book_or_work", ["百年孤独"]),
    ("entity.game.steam-library", "Steam 游戏库", "game_or_media", ["Steam", "游戏库", "游戏"]),
    ("entity.environment.home", "家庭与居住环境", "environment", ["家庭", "家里", "居住环境"]),
    ("entity.concept.autonomy", "自主性", "concept", ["自主性", "自主"]),
    ("entity.concept.dignity", "尊严", "concept", ["尊严"]),
    ("entity.concept.ai-agi", "AI 与 AGI", "concept", ["AI", "AGI"]),
    ("entity.place.beijing", "北京", "place", ["北京"]),
    ("entity.place.coastal-cities", "沿海发达城市", "place", ["沿海", "发达城市"]),
]


def infer_entity_type(record_id: str, body: str) -> str:
    if record_id.startswith("entity.family."): return "family_role"
    if record_id.startswith("entity.friend.") or record_id.startswith("entity.relationship."): return "person"
    if record_id.startswith("entity.place."): return "place"
    if record_id.startswith("entity.school."): return "school_or_organization"
    if record_id.startswith("entity.book."): return "book_or_work"
    if record_id.startswith("entity.object."): return "object"
    if record_id.startswith("entity.environment."): return "environment"
    if record_id.startswith("entity.concept."): return "concept"
    if any(word in body for word in ("学校", "大学", "高中", "初中")): return "school_or_organization"
    if any(word in body for word in ("书", "小说", "阅读")): return "book_or_work"
    return "concept_or_other"


def add_entity(entities: dict[str, dict[str, Any]], entity_id: str, label: str, entity_type: str, aliases: list[str]) -> None:
    row = entities.setdefault(entity_id, {"id": entity_id, "label": label, "entity_type": entity_type, "aliases": [], "identity_status": "recorded", "record_refs": [], "fragment_refs": [], "event_refs": [], "context_refs": [], "mention_count": 0, "first_seen": None, "last_seen": None, "notes": []})
    for value in [label, *aliases]:
        if value and value not in row["aliases"]: row["aliases"].append(value)


_LATIN_ALIAS_PATTERNS: dict[str, "re.Pattern[str]"] = {}


def alias_matches(text: str, alias: str) -> bool:
    """纯拉丁字母/数字别名按词边界匹配，避免 "AI" 命中 "haircut" 这类子串误报；含中文等字符的别名仍是子串匹配。"""
    alias = alias.strip()
    if len(alias) < 2:
        return False
    folded = alias.casefold()
    if folded.isascii() and folded.isalnum():
        pattern = _LATIN_ALIAS_PATTERNS.get(folded)
        if pattern is None:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(folded)}(?![a-z0-9])")
            _LATIN_ALIAS_PATTERNS[folded] = pattern
        return pattern.search(text.casefold()) is not None
    return folded in text.casefold()


def build_entities(rows: list[dict[str, Any]], fragments: list[dict[str, Any]], record_fragment: dict[str, list[str]]) -> list[dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    redirected: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        meta, body = row["meta"], row["body"]
        record_id = meta.get("id", "")
        if meta.get("kind") != "entity" or not record_id: continue
        if record_id in ENTITY_REDIRECTS:
            redirected.append((record_id, row)); continue
        aliases = split_ids(meta.get("aliases")); label = aliases[0] if aliases else record_title(meta, body)
        add_entity(entities, record_id, label, infer_entity_type(record_id, body), aliases)
        entities[record_id]["fragment_refs"].extend(record_fragment.get(record_id, []))
        entities[record_id]["record_refs"].append(record_id)
    for entity_id, label, entity_type, aliases in SEED_ENTITIES:
        add_entity(entities, entity_id, label, entity_type, aliases)
        entities[entity_id]["identity_status"] = "recorded_from_summary"
        entities[entity_id]["notes"].append("v2 迁移种子：由旧摘要中的明确名称建立轻量实体卡，详情仍需回到来源核验。")
    for old_id, row in redirected:
        meta, body = row["meta"], row["body"]
        canonical = canonical_entity_id(old_id)
        if canonical not in entities: continue
        aliases = split_ids(meta.get("aliases"))
        add_entity(entities, canonical, entities[canonical]["label"], entities[canonical]["entity_type"], aliases)
        entities[canonical]["fragment_refs"].extend(record_fragment.get(old_id, []))
        if old_id not in entities[canonical]["record_refs"]: entities[canonical]["record_refs"].append(old_id)
        entities[canonical]["notes"].append(f"已合并 {old_id} 的别名与材料；重定向关系见 relations。")
    for row in rows:
        meta, body = row["meta"], row["body"]; record_id = meta.get("id", "")
        text = f"{record_id} {meta.get('aliases', '')} {body}"
        for entity_id, entity in entities.items():
            if any(alias_matches(text, alias) for alias in entity["aliases"]):
                entity["mention_count"] += 1
                if record_id not in entity["record_refs"]: entity["record_refs"].append(record_id)
                for fragment_id in record_fragment.get(record_id, []):
                    if fragment_id not in entity["fragment_refs"]: entity["fragment_refs"].append(fragment_id)
    for fragment in fragments:
        if fragment["source_kind"] != "conversation-capture": continue
        for entity_id, entity in entities.items():
            if any(alias_matches(fragment["verbatim"], alias) for alias in entity["aliases"]):
                fragment["entity_refs"].append(entity_id)
                if fragment["id"] not in entity["fragment_refs"]: entity["fragment_refs"].append(fragment["id"])
                entity["mention_count"] += 1
    return list(entities.values())


def entity_refs_for(meta: dict[str, str], body: str, entity_by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Alias matches plus explicitly declared entity_refs, resolved through redirects."""
    text = f"{meta.get('id', '')} {meta.get('aliases', '')} {body}"
    refs = {entity_id for entity_id, entity in entity_by_id.items() if any(alias_matches(text, alias) for alias in entity.get("aliases", []))}
    for declared in split_ids(meta.get("entity_refs")):
        canonical = canonical_entity_id(declared)
        if canonical in entity_by_id:
            refs.add(canonical)
    return sorted(refs)


def build_entries(rows: list[dict[str, Any]], record_fragment: dict[str, str], entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entity_by_id = {row["id"]: row for row in entities}; entries = []
    for row in rows:
        meta, body = row["meta"], row["body"]
        if meta.get("kind") not in {"event", "decision", "state"}: continue
        record_id = meta.get("id", ""); d = date_info(meta); salience, basis = salience_for(meta, body)
        entity_refs = entity_refs_for(meta, body, entity_by_id)
        entries.append({"id": f"entry.{slug(record_id)}", "record_id": record_id, "title": record_title(meta, body), "entry_kind": meta.get("kind", "unknown"), "status": meta.get("status", "current"), "confidence": meta.get("confidence", ""), "sensitivity": meta.get("sensitivity", ""), "summary": clean_text(body), "salience": salience, "salience_label": SALIENCE_LABELS[salience], "salience_basis": basis, **d, "phase": meta.get("phase") or "未分期", "domain": meta.get("domain") or "domain.unclassified", "entity_refs": sorted(set(entity_refs)), "unresolved_referents": [], "fragment_refs": record_fragment.get(record_id, []), "record_refs": [record_id], "before_ids": [], "after_ids": [], "relation_refs": {field: split_ids(meta.get(field)) for field in ("related_ids", "supports", "contradicts", "supersedes")}, "legacy_import": True, "note": "来自 v0.6 派生记录；重要性为导入启发式，未来可由原话复核。"})
    dated = sorted((entry for entry in entries if entry.get("date_start")), key=lambda item: (item["date_start"], item["id"]))
    for index, entry in enumerate(dated):
        if index: entry["before_ids"].append(dated[index - 1]["id"])
        if index + 1 < len(dated): entry["after_ids"].append(dated[index + 1]["id"])
    return entries


def build_knowledge(rows: list[dict[str, Any]], record_fragment: dict[str, list[str]], entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entity_by_id = {row["id"]: row for row in entities}; cards = []
    for row in rows:
        meta, body = row["meta"], row["body"]; kind = meta.get("kind", "")
        if kind in {"event", "decision", "state", "entity"}: continue
        record_id = meta.get("id", "")
        if not record_id: continue
        refs = entity_refs_for(meta, body, entity_by_id)
        salience, basis = salience_for(meta, body)
        cards.append({"id": f"card.{slug(record_id)}", "record_id": record_id, "kind": kind, "title": record_title(meta, body), "summary": clean_text(body), "domain": meta.get("domain") or "domain.unclassified", "status": meta.get("status", "current"), "confidence": meta.get("confidence", ""), "salience": salience, "salience_label": SALIENCE_LABELS[salience], "salience_basis": basis, "entity_refs": sorted(set(refs)), "fragment_refs": record_fragment.get(record_id, []), "relation_refs": {field: split_ids(meta.get(field)) for field in ("related_ids", "supports", "contradicts", "supersedes")}, "model_type": meta.get("model_type", ""), "legacy_import": True})
    return cards

def build_contexts(entities: list[dict[str, Any]], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {entity["id"]: entity for entity in entities}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    pair_grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        refs = sorted(set(entry.get("entity_refs", [])))
        for entity_id in refs:
            grouped[(entity_id, entry.get("domain") or "domain.unclassified")].append(entry)
        for index, left in enumerate(refs):
            for right in refs[index + 1:]:
                pair_grouped[(left, right)].append(entry)
    contexts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for (entity_id, domain), group in sorted(grouped.items()):
        if entity_id not in by_id:
            continue
        context_id = f"context.{slug(entity_id)}.{slug(domain)}"
        related = sorted({other for entry in group for other in entry.get("entity_refs", []) if other != entity_id})
        contexts.append({"id": context_id, "kind": "entity-context", "entity_id": entity_id, "entity_ids": [entity_id], "context_key": domain, "label": domain.replace("domain.", ""), "entry_refs": sorted({entry["id"] for entry in group}), "related_entity_ids": related, "facet_policy": "canonical-fragments-with-linked-projections", "note": "情境切片不复制事实，其他档案通过此卡片跳转。"})
        seen_ids.add(context_id); by_id[entity_id]["context_refs"].append(context_id)
    for (left, right), group in sorted(pair_grouped.items()):
        left_label = by_id.get(left, {}).get("label", left)
        right_label = by_id.get(right, {}).get("label", right)
        context_id = f"facet.{slug(left)}.{slug(right)}"
        contexts.append({"id": context_id, "kind": "facet", "entity_id": None, "entity_ids": [left, right], "context_key": f"{left} x {right}", "label": f"{left_label} × {right_label}", "entry_refs": sorted({entry["id"] for entry in group}), "related_entity_ids": [left, right], "facet_policy": "canonical-fragments-with-linked-projections", "note": "跨实体情境卡；同一事实只保留一份，实体档案通过本卡片回到共同故事。"})
        for entity_id in (left, right):
            if entity_id in by_id: by_id[entity_id]["context_refs"].append(context_id)
    for entity in entities:
        entity["context_refs"] = sorted(set(entity.get("context_refs", [])))
    return contexts

def parse_open_loops(path: Path) -> list[dict[str, str]]:
    """Parse structured `- id:` blocks; ignore legend/prose lines and closed loops."""
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if line.startswith("- id:"):
            if current: entries.append(current)
            current = {"id": stripped.removeprefix("- id:").strip()}
            continue
        if current is not None:
            if line.startswith("  ") and ":" in stripped:
                key, value = stripped.split(":", 1)
                current[key.strip()] = value.strip()
            elif line.startswith("- "):
                entries.append(current)
                current = None
            elif not stripped:
                continue
            else:
                entries.append(current)
                current = None
    if current: entries.append(current)
    return entries


def build_followups() -> list[dict[str, Any]]:
    """followups.jsonl 是权威状态；open-loops.md 只作为待导入的种子源。

    每次 build 都把 open-loops.md 中尚未导入的开放回路追加进来（幂等），
    已关闭（answered/declined）的回路永远不会导入；jsonl 中的手工修改不会被覆盖。
    """
    existing = [row for row in jsonl_read(JSONL_FILES["followups"]) if "_parse_error" not in row]
    known_ids = {row.get("id") for row in existing}
    imported: list[dict[str, Any]] = []
    path = ROOT / "memory" / "open-loops.md"
    if path.exists():
        open_statuses = {"pending", "pending-identification", "deferred"}
        for entry in parse_open_loops(path):
            if entry.get("status", "pending") not in open_statuses:
                continue
            loop_id = entry.get("id", "").strip()
            question = entry.get("question", "").strip() or loop_id
            row_id = f"followup.legacy.{slug(loop_id)}"
            if not loop_id or not question or row_id in known_ids:
                continue
            imported.append({"id": row_id, "prompt": question, "context": question, "status": "pending", "due_at": None, "due_rule": "next-relevant-activation", "source_refs": ["memory/open-loops.md"], "created_at": entry.get("asked_on"), "last_checked_at": None, "snooze_until": None, "priority": "normal", "legacy_import": True})
            known_ids.add(row_id)
    return existing + imported


def build_current_state(rows: list[dict[str, Any]], followups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    current = [row for row in rows if row["meta"].get("status") == "current"]
    def card(row: dict[str, Any], category: str) -> dict[str, Any]:
        meta, body = row["meta"], row["body"]
        return {"id": meta.get("id"), "category": category, "title": record_title(meta, body), "summary": clean_text(body), "confidence": meta.get("confidence", ""), "date": meta.get("last_confirmed") or meta.get("valid_from"), "record_ref": meta.get("id")}
    events = [row for row in current if row["meta"].get("kind") == "event"]
    examples = [card(row, "lived-example") for row in sorted(events, key=lambda row: (row["meta"].get("valid_from") or row["meta"].get("last_confirmed") or "", row["meta"].get("id", "")), reverse=True)[:10]]
    today = date.today().isoformat()
    open_followups = [row for row in (followups or []) if followup_open(row)]
    due_followups = [row for row in open_followups if followup_is_due(row, today)]
    undated = [row for row in open_followups if not followup_due_day(row)]
    next_items = [{"id": row.get("id"), "prompt": row.get("prompt") or row.get("question"), "due_at": row.get("due_at"), "status": "due"} for row in sorted(due_followups, key=lambda row: (str(row.get("due_at")), row.get("id", "")))[:5]]
    next_items += [{"id": row.get("id"), "prompt": row.get("prompt") or row.get("question"), "due_at": None, "status": "undated"} for row in sorted(undated, key=lambda row: row.get("id", ""))[:5]]
    return {"version": V2_VERSION, "as_of": today, "core": [card(row, "core") for row in current if row["meta"].get("kind") in {"model", "value", "rule", "heuristic"}][:12], "conditions": [card(row, "condition") for row in current if row["meta"].get("kind") == "state"][:18], "tensions": [card(row, "tension") for row in current if row["meta"].get("kind") == "decision"][:12], "lived_examples": examples, "next": next_items, "format": "core + conditions + lived_examples + tensions + next"}

def build_relations(rows: list[dict[str, Any]], contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid_ids = {row["meta"].get("id") for row in rows if row["meta"].get("id")} | {row["meta"].get("id") for row in load_branches() if row["meta"].get("id")}; relations = []
    for row in rows:
        meta = row["meta"]; source = canonical_entity_id(meta.get("id", ""))
        if not source: continue
        for field in ("related_ids", "supports", "contradicts", "supersedes", "parent_ids"):
            for target_raw in split_ids(meta.get(field)):
                target = canonical_entity_id(target_raw)
                relations.append({"id": f"relation.{slug(source)}.{slug(field)}.{slug(target)}", "source": source, "target": target, "type": field, "provenance": "record-frontmatter", "resolved": target in valid_ids})
    for context in contexts:
        sources = context.get("entity_ids") or ([context.get("entity_id")] if context.get("entity_id") else [])
        for source in sources:
            for target in context.get("related_entity_ids", []):
                if not source or source == target:
                    continue
                relations.append({"id": f"relation.{slug(context['id'])}.{slug(source)}.{slug(target)}", "source": source, "target": target, "type": "contextual-cooccurrence", "context_id": context["id"], "provenance": "v2-derived", "resolved": True})
    for old_id, new_id in ENTITY_REDIRECTS.items():
        relations.append({"id": f"relation.redirect.{slug(old_id)}", "source": old_id, "target": new_id, "type": "entity-redirect", "provenance": "user-correction-2026-08-22", "resolved": True})
    return relations


def write_pages(entities: list[dict[str, Any]], entries: list[dict[str, Any]], fragments: dict[str, dict[str, Any]], contexts: list[dict[str, Any]]) -> None:
    for folder in (ENTITY_PAGES, EVENT_PAGES):
        folder.mkdir(parents=True, exist_ok=True)
    entry_by_id = {entry["id"]: entry for entry in entries}; contexts_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for context in contexts:
        for entity_id in ([context["entity_id"]] if context.get("entity_id") else []) + list(context.get("entity_ids") or []):
            contexts_by_entity[entity_id].append(context)
    entity_page_names: set[str] = set()
    for entity in entities:
        lines = [f"# {entity['label']}", "", f"- 类型：{entity['entity_type']}", f"- 身份状态：{entity['identity_status']}", f"- 提及次数：{entity['mention_count']}", "", "## 直接材料", ""]
        for fragment_id in entity.get("fragment_refs", []):
            fragment = fragments.get(fragment_id)
            if fragment: lines.append(f"- [{fragment['fidelity']}] {fragment['verbatim']}")
        lines.extend(["", "## 关联故事（不删连接）", ""]); seen: set[str] = set()
        for context in contexts_by_entity.get(entity["id"], []):
            lines.append(f"### {context['label']}")
            for entry_id in context.get("entry_refs", []):
                if entry_id in seen or entry_id not in entry_by_id: continue
                seen.add(entry_id); entry = entry_by_id[entry_id]
                lines.append(f"- `{entry['date_text']}` [{entry['salience_label']}] {entry['title']} — {entry['record_id']}")
        lines.extend(["", "## 说明", "", "事实只保留一份，其他人物、地点、学校、书、游戏和概念通过情境卡片跳转；档案不为追求‘纯洁’删除社会连接。", ""])
        page_name = f"{slug(entity['id'])}.md"
        entity_page_names.add(page_name)
        write_text_atomic(ENTITY_PAGES / page_name, "\n".join(lines))
    event_page_names: set[str] = set()
    for entry in entries:
        lines = [f"# {entry['title']}", "", f"- 日期：{entry['date_text']}", f"- 记忆权重：{entry['salience_label']} ({entry['salience']})", f"- 类型：{entry['entry_kind']}", "", "## 证据", ""]
        for fragment_id in entry.get("fragment_refs", []):
            fragment = fragments.get(fragment_id)
            if fragment: lines.extend([f"> {fragment['verbatim']}", f"> 来源：{', '.join(fragment.get('source_refs', []))}；保真度：{fragment.get('fidelity')}", ""])
        lines.extend(["## 相关实体", "", *[f"- `{ref}`" for ref in entry.get("entity_refs", [])], ""])
        page_name = f"{slug(entry['id'])}.md"
        event_page_names.add(page_name)
        write_text_atomic(EVENT_PAGES / page_name, "\n".join(lines))
    for folder, written in ((ENTITY_PAGES, entity_page_names), (EVENT_PAGES, event_page_names)):
        for stale in folder.glob("*.md"):
            if stale.name not in written:
                stale.unlink()


def _build_archive() -> dict[str, Any]:
    V2_ROOT.mkdir(parents=True, exist_ok=True)
    rows = load_records()
    fragments, record_fragment = build_fragments(rows)
    entities = build_entities(rows, fragments, record_fragment)
    entries = build_entries(rows, record_fragment, entities)
    entity_map = {entity["id"]: entity for entity in entities}
    for entry in entries:
        for entity_id in entry.get("entity_refs", []):
            entity = entity_map.get(entity_id)
            if not entity:
                continue
            entity["event_refs"].append(entry["id"])
            if entry.get("date_start"):
                dates = [value for value in (entity.get("first_seen"), entry["date_start"]) if value]
                entity["first_seen"] = min(dates) if dates else entry["date_start"]
                dates = [value for value in (entity.get("last_seen"), entry.get("date_end") or entry.get("date_start")) if value]
                entity["last_seen"] = max(dates) if dates else (entry.get("date_end") or entry.get("date_start"))
    for entity in entities:
        entity["event_refs"] = sorted(set(entity.get("event_refs", [])))
    knowledge = build_knowledge(rows, record_fragment, entities)
    contexts = build_contexts(entities, entries)
    followups = build_followups()
    hypotheses = jsonl_read(JSONL_FILES["hypotheses"])
    relations = build_relations(rows, contexts)
    current_state = build_current_state(rows, followups)
    for key, value in (("fragments", fragments), ("entities", entities), ("events", entries), ("knowledge", knowledge), ("contexts", contexts), ("followups", followups), ("hypotheses", hypotheses), ("relations", relations)):
        jsonl_write(JSONL_FILES[key], value)
    write_text_atomic(V2_ROOT / "current-state.json", json.dumps(current_state, ensure_ascii=False, indent=2) + "\n")
    fragment_map = {row["id"]: row for row in fragments}
    write_pages(entities, entries, fragment_map, contexts)
    index: dict[str, Any] = {"version": V2_VERSION, "generated_at": datetime.now().isoformat(timespec="seconds"), "by_entity": {}, "by_date": defaultdict(list), "by_record": {}, "salience_counts": defaultdict(int), "fidelity_counts": defaultdict(int)}
    for entity in entities:
        index["by_entity"][entity["id"]] = {"entry_refs": entity["event_refs"], "record_refs": entity["record_refs"], "fragment_refs": entity["fragment_refs"], "context_refs": entity["context_refs"]}
    for entry in entries:
        index["by_record"][entry["record_id"]] = entry["id"]
        index["salience_counts"][entry["salience_label"]] += 1
        if entry.get("date_start"): index["by_date"][entry["date_start"]].append(entry["id"])
    for fragment in fragments: index["fidelity_counts"][fragment["fidelity"]] += 1
    index["by_date"] = dict(index["by_date"]); index["salience_counts"] = dict(index["salience_counts"]); index["fidelity_counts"] = dict(index["fidelity_counts"])
    write_text_atomic(V2_ROOT / "index.json", json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    manifest = {"version": V2_VERSION, "skill_version": skill_version(), "schema": "timeline + entities + immutable fragments + contextual facets + followups + hypotheses", "generated_at": index["generated_at"], "counts": {"legacy_records": len(rows), "timeline_entries": len(entries), "entities": len(entities), "fragments": len(fragments), "contexts": len(contexts), "knowledge": len(knowledge), "followups": len(followups), "hypotheses": len(hypotheses), "relations": len(relations)}, "legacy_summary_debt": sum(row["fidelity"] == "summary_only" for row in fragments), "verbatim_captures": sum(row["fidelity"] == "verbatim" for row in fragments), "single_salience_scale": {"3": "主轴", "2": "关键", "1": "关联", "0": "提及"}, "entity_redirects": ENTITY_REDIRECTS, "raw_capture_policy": "personal-understanding updates must be captured verbatim before derivation", "entity_policy": "every referential mention may get a small card; ambiguous identity is metadata, not a discarded junk node", "cross_context_policy": "canonical fragments are stored once and projected through linked context cards"}
    write_text_atomic(V2_ROOT / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def build_archive() -> dict[str, Any]:
    """Serialize full rebuilds, including stale generated-page cleanup."""
    with mutation_lock(ROOT):
        return _build_archive()


def skill_version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or V2_VERSION
    except OSError:
        return V2_VERSION


def _read_json_object(path: Path) -> tuple[dict[str, Any], str | None]:
    """读取 JSON 对象；损坏时返回空对象和错误说明，绝不抛异常。"""
    if not path.exists():
        return {}, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"{path.name}: {exc}"
    return (value if isinstance(value, dict) else {}), None if isinstance(value, dict) else f"{path.name}: 顶层不是 JSON 对象"


def v2_audit(strict: bool = False) -> dict[str, Any]:
    manifest, manifest_error = _read_json_object(V2_ROOT / "manifest.json")
    errors: list[dict[str, Any]] = []
    if manifest_error:
        errors.append({"code": "manifest-corrupt", "detail": manifest_error})
    if not (V2_ROOT / "manifest.json").exists():
        errors.append({"code": "missing-manifest"})
    data = {name: jsonl_read(path) for name, path in JSONL_FILES.items()}
    warnings: list[dict[str, Any]] = []; seen: dict[str, tuple[str, int]] = {}
    for name, rows in data.items():
        for line, row in enumerate(rows, 1):
            if "_parse_error" in row:
                errors.append({"code": "invalid-jsonl", "file": name, "line": row["_parse_error"]}); continue
            item_id = row.get("id")
            if not item_id: errors.append({"code": "missing-id", "file": name, "line": line}); continue
            if item_id in seen: errors.append({"code": "duplicate-v2-id", "id": item_id, "first": seen[item_id], "second": (name, line)})
            seen[item_id] = (name, line)
    fragments = {row.get("id"): row for row in data["fragments"] if row.get("id")}; entities = {row.get("id"): row for row in data["entities"] if row.get("id")}; entries = {row.get("id"): row for row in data["events"] if row.get("id")}; context_ids = {row.get("id") for row in data["contexts"]}
    errors.extend(capture_fragment_parity_errors(fragments.keys(), ROOT))
    record_ids = {row["meta"].get("id") for row in load_records() if row["meta"].get("id")}
    for fragment in fragments.values():
        if fragment.get("verbatim_sha256") != sha256_text(fragment.get("verbatim", "")): errors.append({"code": "fragment-hash-mismatch", "id": fragment.get("id")})
        for ref in fragment.get("record_refs", []):
            if ref not in record_ids: warnings.append({"code": "fragment-record-not-found", "id": fragment.get("id"), "record": ref})
    for entity in entities.values():
        for ref in entity.get("fragment_refs", []):
            if ref not in fragments: errors.append({"code": "entity-fragment-orphan", "entity": entity.get("id"), "fragment": ref})
        for ref in entity.get("context_refs", []):
            if ref not in context_ids: errors.append({"code": "entity-context-orphan", "entity": entity.get("id"), "context": ref})
    for entry in entries.values():
        if entry.get("salience") not in {0, 1, 2, 3}: errors.append({"code": "invalid-salience", "id": entry.get("id"), "value": entry.get("salience")})
        for ref in entry.get("fragment_refs", []):
            if ref not in fragments: errors.append({"code": "entry-fragment-orphan", "entry": entry.get("id"), "fragment": ref})
        for ref in entry.get("entity_refs", []):
            if ref not in entities: errors.append({"code": "entry-entity-orphan", "entry": entry.get("id"), "entity": ref})
    legacy_capture_debt = []
    for row in load_records():
        meta = row["meta"]
        if "current-conversation" in split_ids(meta.get("source_refs")) and not split_ids(meta.get("verbatim_refs")):
            legacy_capture_debt.append(meta.get("id"))
    if legacy_capture_debt:
        warnings.append({"code": "legacy-missing-verbatim-capture", "count": len(legacy_capture_debt), "sample": legacy_capture_debt[:12], "action": "旧摘要无法可靠恢复原话；未来更新必须先 capture"})
    due = [row for row in data["followups"] if followup_is_due(row)]
    if due: warnings.append({"code": "followups-due", "count": len(due), "ids": [row.get("id") for row in due]})
    metrics = {"errors": len(errors), "warnings": len(warnings), "due_followups": len(due), "summary_only_fragments": sum(row.get("fidelity") == "summary_only" for row in fragments.values()), "verbatim_fragments": sum(row.get("fidelity") == "verbatim" for row in fragments.values())}
    return {"version": V2_VERSION, "status": "failed" if errors or (strict and warnings) else ("warnings" if warnings else "clean"), "errors": errors, "warnings": warnings, "metrics": metrics, "manifest": manifest}


def load_v2() -> dict[str, Any]:
    data = {name: jsonl_read(path) for name, path in JSONL_FILES.items()}
    manifest, manifest_error = _read_json_object(V2_ROOT / "manifest.json")
    current_state, state_error = _read_json_object(V2_ROOT / "current-state.json")
    load_errors = [error for error in (manifest_error, state_error) if error]
    if load_errors:
        data["_load_errors"] = load_errors
    data["manifest"] = manifest
    data["current_state"] = current_state
    return data
