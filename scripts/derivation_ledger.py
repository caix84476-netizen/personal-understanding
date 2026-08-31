#!/usr/bin/env python3
"""Capture → derivation closure ledger with journaled, process-safe mutations."""
from __future__ import annotations
import json, re, uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from storage import atomic_write_text, mutation_lock

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
FINAL_STATUSES = {"derived", "no-derivation-needed"}; VALID_STATUSES = {"pending", *FINAL_STATUSES}
def now_iso() -> str: return datetime.now().astimezone().isoformat(timespec="seconds")
def ledger_path(root: Path = DEFAULT_ROOT) -> Path: return root / "memory" / "derivation-ledger.json"
def journal_path(root: Path = DEFAULT_ROOT) -> Path: return root / "memory" / "derivation-journal.jsonl"

def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8")); return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError): return {}
def _payload(root: Path) -> dict[str, Any]:
    raw = _read_json(ledger_path(root)); captures = raw.get("captures")
    return {"schema_version": raw.get("schema_version", "2.0.0"), "revision": int(raw.get("revision", 0) or 0), "captures": captures if isinstance(captures, dict) else {}}
def load_ledger(root: Path = DEFAULT_ROOT) -> dict[str, dict[str, Any]]: return _payload(root)["captures"]

def _commit(entries: dict[str, dict[str, Any]], root: Path, action: str, capture_id: str | None = None) -> int:
    current = _payload(root); revision = current["revision"] + 1
    payload = {"schema_version": "2.0.0", "revision": revision, "updated_at": now_iso(), "captures": dict(sorted(entries.items()))}
    atomic_write_text(ledger_path(root), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    journal_path(root).parent.mkdir(parents=True, exist_ok=True)
    event = {"operation_id": uuid.uuid4().hex, "at": now_iso(), "action": action, "capture_id": capture_id, "revision": revision}
    with journal_path(root).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"); handle.flush()
    return revision

def save_ledger(entries: dict[str, dict[str, Any]], root: Path = DEFAULT_ROOT) -> None:
    """Compatibility writer that merges with a freshly read projection under lock."""
    with mutation_lock(root):
        fresh = load_ledger(root); fresh.update(entries); _commit(fresh, root, "ledger-merge")

def discover_captures(root: Path = DEFAULT_ROOT) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}; paths = list((root / "sources" / "conversation").glob("*.json")) + list((root / "sources" / "images").glob("*.json"))
    for path in sorted(set(paths)):
        meta = _read_json(path); capture_id = str(meta.get("capture_id", "")).strip()
        if ID_RE.fullmatch(capture_id): result[capture_id] = {"capture_id": capture_id, "source_path": str(meta.get("source_path") or ""), "captured_at": meta.get("captured_at"), "message_kind": meta.get("message_kind"), "content_sha256": meta.get("utf8_sha256") or meta.get("sha256"), "metadata_path": path.relative_to(root).as_posix()}
    return result

def parse_frontmatter(path: Path) -> dict[str, str]:
    try: lines = path.read_text(encoding="utf-8").splitlines()
    except OSError: return {}
    if not lines or lines[0].strip() != "---": return {}
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---": break
        if ":" in line: key, value = line.split(":", 1); data[key.strip()] = value.strip()
    return data
def _split(value: str | None) -> list[str]: return [x.strip() for x in re.split(r"[;,]", value or "") if x.strip()]

def record_capture_links(root: Path = DEFAULT_ROOT) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    captures = discover_captures(root); by_source: dict[str, set[str]] = {}
    for cid, meta in captures.items():
        if meta["source_path"]: by_source.setdefault(meta["source_path"], set()).add(cid)
    c2r = {cid: set() for cid in captures}; r2c: dict[str, set[str]] = {}
    for path in sorted((root / "memory" / "records").glob("*.md")):
        meta = parse_frontmatter(path); rid = meta.get("id")
        if not rid: continue
        linked = {ref.removeprefix("fragment.capture.") for ref in _split(meta.get("verbatim_refs")) if ref.removeprefix("fragment.capture.") in captures}
        for ref in _split(meta.get("source_refs")):
            linked.update(by_source.get(ref, set()))
            if ref.startswith("sources/conversation/") and Path(ref).stem in captures: linked.add(Path(ref).stem)
        if linked:
            r2c[rid] = linked
            for cid in linked: c2r.setdefault(cid, set()).add(rid)
    return c2r, r2c

def _entry(capture_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    return {"capture_id": capture_id, "status": "pending", "source_path": meta.get("source_path"), "captured_at": meta.get("captured_at"), "message_kind": meta.get("message_kind"), "content_sha256": meta.get("content_sha256"), "record_ids": [], "opened_at": now_iso(), "finalized_at": None, "finalization_reason": None, "history": [{"at": now_iso(), "action": "capture-registered"}]}

def register_capture(capture_id: str, *, source_path: str, captured_at: str | None = None, message_kind: str | None = None, content_sha256: str | None = None, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    if not ID_RE.fullmatch(capture_id): raise ValueError("invalid capture id")
    with mutation_lock(root):
        entries = load_ledger(root); meta = {"source_path": source_path, "captured_at": captured_at, "message_kind": message_kind, "content_sha256": content_sha256}; entry = entries.get(capture_id)
        if entry is None:
            entry = _entry(capture_id, meta); entries[capture_id] = entry; _commit(entries, root, "capture-registered", capture_id)
        return entry

def link_record(capture_id: str, record_id: str, *, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    with mutation_lock(root):
        entries = load_ledger(root); captures = discover_captures(root)
        if capture_id not in captures: raise ValueError(f"capture does not exist: {capture_id}")
        entry = entries.get(capture_id) or _entry(capture_id, captures[capture_id]); ids = sorted(set(entry.get("record_ids", [])) | {record_id})
        if ids != entry.get("record_ids", []):
            entry["record_ids"] = ids; entry.setdefault("history", []).append({"at": now_iso(), "action": "record-linked", "record_id": record_id}); entries[capture_id] = entry; _commit(entries, root, "record-linked", capture_id)
        return entry

def finalize_capture(capture_id: str, disposition: str, reason: str = "", *, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    if disposition not in FINAL_STATUSES: raise ValueError("invalid disposition")
    with mutation_lock(root):
        entries = load_ledger(root); captures = discover_captures(root)
        if capture_id not in captures: raise ValueError(f"capture does not exist: {capture_id}")
        entry = entries.get(capture_id) or _entry(capture_id, captures[capture_id]); linked, _ = record_capture_links(root); ids = sorted(set(entry.get("record_ids", [])) | linked.get(capture_id, set()))
        if disposition == "derived" and not ids: raise ValueError("cannot finalize as derived without at least one linked record")
        if disposition == "no-derivation-needed" and len(reason.strip()) < 4: raise ValueError("no-derivation-needed requires a concrete reason")
        entry.update({"record_ids": ids, "status": disposition, "finalized_at": now_iso(), "finalization_reason": reason.strip() or "derived records linked and checked"}); entry.setdefault("history", []).append({"at": now_iso(), "action": "capture-finalized", "status": disposition, "record_ids": ids}); entries[capture_id] = entry; _commit(entries, root, "capture-finalized", capture_id)
        from turn_receipts import mark_closed_for_capture
        mark_closed_for_capture(capture_id, disposition, root); return entry

def repair_ledger(root: Path = DEFAULT_ROOT) -> dict[str, int]:
    """Rebuild the projection from immutable captures and record references."""
    with mutation_lock(root):
        captures = discover_captures(root); linked, _ = record_capture_links(root); old = load_ledger(root); rebuilt: dict[str, dict[str, Any]] = {}; created = 0
        for cid, meta in captures.items():
            created += int(cid not in old); prior = old.get(cid, _entry(cid, meta)); ids = sorted(linked.get(cid, set()))
            if ids: status, reason = "derived", prior.get("finalization_reason") or "repair: linked record discovered"
            elif prior.get("status") == "no-derivation-needed": status, reason = "no-derivation-needed", prior.get("finalization_reason")
            else: status, reason = "pending", None
            prior.update({"record_ids": ids, "status": status, "finalization_reason": reason}); rebuilt[cid] = prior
        _commit(rebuilt, root, "ledger-repaired")
        return {"captures": len(captures), "created": created, "repaired": len(rebuilt), "pending": sum(x["status"] == "pending" for x in rebuilt.values())}

def bootstrap_ledger(root: Path = DEFAULT_ROOT) -> dict[str, int]: return repair_ledger(root)

def audit_ledger(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    captures = discover_captures(root); entries = load_ledger(root); linked, _ = record_capture_links(root); record_ids = {parse_frontmatter(p).get("id") for p in (root / "memory" / "records").glob("*.md")}; errors: list[dict[str, Any]] = []; warnings: list[dict[str, Any]] = []
    for cid in sorted(captures):
        if cid not in entries: warnings.append({"code": "capture-untracked", "capture_id": cid})
    for cid, entry in sorted(entries.items()):
        if cid not in captures: errors.append({"code": "ledger-capture-missing", "capture_id": cid}); continue
        status = entry.get("status"); actual = linked.get(cid, set()); declared = set(entry.get("record_ids", []))
        if status not in VALID_STATUSES: errors.append({"code": "invalid-derivation-status", "capture_id": cid, "status": status})
        if missing := sorted(x for x in declared if x not in record_ids): errors.append({"code": "ledger-record-missing", "capture_id": cid, "record_ids": missing})
        if status == "pending": warnings.append({"code": "capture-pending-derivation", "capture_id": cid, "linked_records": sorted(actual | declared)})
        if status == "derived" and not (actual | declared): errors.append({"code": "capture-derived-without-record", "capture_id": cid})
        if status == "derived" and actual != declared: warnings.append({"code": "capture-record-link-drift", "capture_id": cid, "ledger": sorted(declared), "actual": sorted(actual)})
        if status == "no-derivation-needed" and not str(entry.get("finalization_reason") or "").strip(): errors.append({"code": "capture-no-derivation-without-reason", "capture_id": cid})
    pending = sorted(cid for cid, entry in entries.items() if entry.get("status") == "pending")
    return {"status": "failed" if errors else ("warnings" if warnings else "clean"), "counts": {"captures": len(captures), "ledger_entries": len(entries), "pending": len(pending), "derived": sum(x.get("status") == "derived" for x in entries.values()), "no_derivation_needed": sum(x.get("status") == "no-derivation-needed" for x in entries.values())}, "errors": errors, "warnings": warnings, "pending_capture_ids": pending}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--repair", action="store_true"); args = ap.parse_args()
    print(json.dumps(repair_ledger() if args.repair else audit_ledger(), ensure_ascii=False, indent=2))
