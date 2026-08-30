#!/usr/bin/env python3
"""Track capture -> derived-record closure without mutating immutable capture metadata."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
FINAL_STATUSES = {"derived", "no-derivation-needed"}
VALID_STATUSES = {"pending", *FINAL_STATUSES}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ledger_path(root: Path = DEFAULT_ROOT) -> Path:
    return root / "memory" / "derivation-ledger.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_ledger(root: Path = DEFAULT_ROOT) -> dict[str, dict[str, Any]]:
    path = ledger_path(root)
    if not path.exists():
        return {}
    raw = _read_json(path)
    entries = raw.get("captures", {})
    return entries if isinstance(entries, dict) else {}


def save_ledger(entries: dict[str, dict[str, Any]], root: Path = DEFAULT_ROOT) -> None:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "1.0.0", "updated_at": now_iso(), "captures": dict(sorted(entries.items()))}
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def discover_captures(root: Path = DEFAULT_ROOT) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    paths = list((root / "sources" / "conversation").glob("*.json"))
    paths += list((root / "sources" / "conversation").glob("*.attachment.json"))
    paths += list((root / "sources" / "images").glob("*.json"))
    for path in sorted(set(paths)):
        meta = _read_json(path)
        capture_id = str(meta.get("capture_id", "")).strip()
        if not ID_RE.fullmatch(capture_id):
            continue
        source_path = str(meta.get("source_path") or "").strip()
        result[capture_id] = {
            "capture_id": capture_id,
            "source_path": source_path,
            "captured_at": meta.get("captured_at"),
            "message_kind": meta.get("message_kind"),
            "content_sha256": meta.get("utf8_sha256") or meta.get("sha256"),
            "metadata_path": path.relative_to(root).as_posix(),
        }
    return result


def parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return data


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in re.split(r"[;,]", value or "") if item.strip()]


def record_capture_links(root: Path = DEFAULT_ROOT) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return capture->record and record->capture maps using verbatim refs and source paths."""
    captures = discover_captures(root)
    source_to_capture: dict[str, set[str]] = {}
    for capture_id, meta in captures.items():
        if meta.get("source_path"):
            source_to_capture.setdefault(str(meta["source_path"]), set()).add(capture_id)
    capture_to_records: dict[str, set[str]] = {capture_id: set() for capture_id in captures}
    record_to_captures: dict[str, set[str]] = {}
    for path in sorted((root / "memory" / "records").glob("*.md")):
        meta = parse_frontmatter(path)
        record_id = meta.get("id")
        if not record_id:
            continue
        linked: set[str] = set()
        for ref in _split(meta.get("verbatim_refs")):
            capture_id = ref.removeprefix("fragment.capture.")
            if capture_id in captures:
                linked.add(capture_id)
        for ref in _split(meta.get("source_refs")):
            linked.update(source_to_capture.get(ref, set()))
            if ref.startswith("sources/conversation/"):
                stem = Path(ref).stem
                if stem in captures:
                    linked.add(stem)
        if linked:
            record_to_captures[record_id] = linked
            for capture_id in linked:
                capture_to_records.setdefault(capture_id, set()).add(record_id)
    return capture_to_records, record_to_captures


def register_capture(capture_id: str, *, source_path: str, captured_at: str | None = None,
                     message_kind: str | None = None, content_sha256: str | None = None,
                     root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    if not ID_RE.fullmatch(capture_id):
        raise ValueError(f"invalid capture_id: {capture_id}")
    entries = load_ledger(root)
    if capture_id in entries:
        return entries[capture_id]
    entry = {
        "capture_id": capture_id,
        "status": "pending",
        "source_path": source_path,
        "captured_at": captured_at,
        "message_kind": message_kind,
        "content_sha256": content_sha256,
        "record_ids": [],
        "opened_at": now_iso(),
        "finalized_at": None,
        "finalization_reason": None,
        "history": [{"at": now_iso(), "action": "capture-registered", "status": "pending"}],
    }
    entries[capture_id] = entry
    save_ledger(entries, root)
    return entry


def link_record(capture_id: str, record_id: str, *, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    captures = discover_captures(root)
    if capture_id not in captures:
        raise ValueError(f"capture does not exist: {capture_id}")
    entries = load_ledger(root)
    entry = entries.get(capture_id) or register_capture(capture_id, root=root, **{k: captures[capture_id].get(k) for k in ("source_path", "captured_at", "message_kind", "content_sha256")})
    record_ids = list(dict.fromkeys([*entry.get("record_ids", []), record_id]))
    entry["record_ids"] = record_ids
    if entry.get("status") == "no-derivation-needed":
        entry["status"] = "pending"
        entry["finalized_at"] = None
        entry["finalization_reason"] = None
        entry.setdefault("history", []).append({"at": now_iso(), "action": "reopened-by-record-link", "record_id": record_id, "status": "pending"})
    else:
        entry.setdefault("history", []).append({"at": now_iso(), "action": "record-linked", "record_id": record_id, "status": entry.get("status", "pending")})
    entries[capture_id] = entry
    save_ledger(entries, root)
    return entry


def finalize_capture(capture_id: str, disposition: str, reason: str = "", *, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    if disposition not in FINAL_STATUSES:
        raise ValueError(f"invalid disposition: {disposition}")
    captures = discover_captures(root)
    if capture_id not in captures:
        raise ValueError(f"capture does not exist: {capture_id}")
    entries = load_ledger(root)
    entry = entries.get(capture_id) or register_capture(capture_id, root=root, **{k: captures[capture_id].get(k) for k in ("source_path", "captured_at", "message_kind", "content_sha256")})
    linked, _ = record_capture_links(root)
    record_ids = sorted(set(entry.get("record_ids", [])) | linked.get(capture_id, set()))
    if disposition == "derived" and not record_ids:
        raise ValueError("cannot finalize as derived without at least one linked record")
    if disposition == "no-derivation-needed" and len(reason.strip()) < 4:
        raise ValueError("no-derivation-needed requires a concrete reason")
    entry["record_ids"] = record_ids
    entry["status"] = disposition
    entry["finalized_at"] = now_iso()
    entry["finalization_reason"] = reason.strip() or "derived records linked and checked"
    entry.setdefault("history", []).append({"at": now_iso(), "action": "capture-finalized", "status": disposition, "reason": entry["finalization_reason"], "record_ids": record_ids})
    entries[capture_id] = entry
    save_ledger(entries, root)
    return entry


def bootstrap_ledger(root: Path = DEFAULT_ROOT) -> dict[str, int]:
    captures = discover_captures(root)
    linked, _ = record_capture_links(root)
    entries = load_ledger(root)
    created = 0
    for capture_id, meta in captures.items():
        if capture_id in entries:
            continue
        records = sorted(linked.get(capture_id, set()))
        status = "derived" if records else "pending"
        reason = "bootstrap: existing linked records found" if records else None
        entries[capture_id] = {
            "capture_id": capture_id,
            "status": status,
            "source_path": meta.get("source_path"),
            "captured_at": meta.get("captured_at"),
            "message_kind": meta.get("message_kind"),
            "content_sha256": meta.get("content_sha256"),
            "record_ids": records,
            "opened_at": now_iso(),
            "finalized_at": now_iso() if records else None,
            "finalization_reason": reason,
            "history": [{"at": now_iso(), "action": "ledger-bootstrap", "status": status, "record_ids": records}],
        }
        created += 1
    save_ledger(entries, root)
    return {"captures": len(captures), "created": created, "pending": sum(e.get("status") == "pending" for e in entries.values())}


def audit_ledger(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    captures = discover_captures(root)
    entries = load_ledger(root)
    linked, _ = record_capture_links(root)
    record_ids = {parse_frontmatter(path).get("id") for path in (root / "memory" / "records").glob("*.md")}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for capture_id in sorted(captures):
        if capture_id not in entries:
            warnings.append({"code": "capture-untracked", "capture_id": capture_id})
    for capture_id, entry in sorted(entries.items()):
        if capture_id not in captures:
            errors.append({"code": "ledger-capture-missing", "capture_id": capture_id})
            continue
        status = entry.get("status")
        if status not in VALID_STATUSES:
            errors.append({"code": "invalid-derivation-status", "capture_id": capture_id, "status": status})
        actual_records = linked.get(capture_id, set())
        declared_records = set(entry.get("record_ids", []))
        missing_records = sorted(record_id for record_id in declared_records if record_id not in record_ids)
        if missing_records:
            errors.append({"code": "ledger-record-missing", "capture_id": capture_id, "record_ids": missing_records})
        if status == "pending":
            warnings.append({"code": "capture-pending-derivation", "capture_id": capture_id, "linked_records": sorted(actual_records | declared_records)})
        if status == "derived" and not (actual_records | declared_records):
            errors.append({"code": "capture-derived-without-record", "capture_id": capture_id})
        if status == "derived" and declared_records != actual_records:
            warnings.append({"code": "capture-record-link-drift", "capture_id": capture_id, "ledger": sorted(declared_records), "actual": sorted(actual_records)})
        if status == "no-derivation-needed" and not str(entry.get("finalization_reason") or "").strip():
            errors.append({"code": "capture-no-derivation-without-reason", "capture_id": capture_id})
    pending = [capture_id for capture_id, entry in entries.items() if entry.get("status") == "pending"]
    return {
        "status": "failed" if errors else ("warnings" if warnings else "clean"),
        "counts": {"captures": len(captures), "ledger_entries": len(entries), "pending": len(pending), "derived": sum(e.get("status") == "derived" for e in entries.values()), "no_derivation_needed": sum(e.get("status") == "no-derivation-needed" for e in entries.values())},
        "errors": errors,
        "warnings": warnings,
        "pending_capture_ids": sorted(pending),
    }
