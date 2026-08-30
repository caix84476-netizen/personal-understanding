#!/usr/bin/env python3
"""Local-only MCP server for personal-understanding v2."""
from __future__ import annotations
import datetime as dt
import hashlib, json, os, re, subprocess, sys
from pathlib import Path
from typing import Any
from derivation_ledger import audit_ledger, discover_captures, finalize_capture, link_record, register_capture
from v2_archive import skill_version, write_text_atomic

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RECORDS = ROOT / "memory" / "records"
V2 = ROOT / "memory" / "v2"
CAPTURES = ROOT / "sources" / "conversation"
VALID_KINDS = {"fact", "state", "event", "preference", "rule", "heuristic", "value", "decision", "model", "entity"}
VALID_SENSITIVITY = {"ordinary", "private", "highly-private"}
VALID_CONFIDENCE = {"high", "medium-high", "medium", "low", "very-high", "low-medium"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]+$")


def text_result(text: str, *, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def run_script(name: str, args: list[str]) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(SCRIPTS / name), *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    output = (proc.stdout + ("\n" if proc.stdout and proc.stderr else "") + proc.stderr).strip()
    return proc.returncode, output


def rebuild_and_validate() -> tuple[int, str]:
    rebuild_code, rebuild_output = run_script("rebuild_views.py", [])
    # Any MCP write is part of a completion-sensitive workflow. A pending
    # capture must fail the post-write gate instead of being downgraded to a
    # warning that the model can accidentally ignore.
    validate_code, validate_output = run_script("validate_memory.py", ["--require-closed-captures"])
    return max(rebuild_code, validate_code), f"{rebuild_output}\n{validate_output}".strip()


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {"name": "personal_catalog", "description": "Read the v2 global survey. Must first complete this turn's preflight capture and provide capture_id; otherwise the read is refused.", "inputSchema": {"type": "object", "properties": {"view": {"type": "string", "enum": ["survey", "routing", "full"], "default": "survey"}, "query": {"type": "string"}, "capture_id": {"type": "string"}}, "required": ["capture_id"], "additionalProperties": False}},
        {"name": "personal_retrieve", "description": "Read probe/deep by v2 events, entities, and context cards. Must first complete this turn's preflight capture and provide capture_id; otherwise the read is refused.", "inputSchema": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}}, "level": {"type": "string", "enum": ["probe", "deep"], "default": "probe"}, "query": {"type": "string"}, "capture_id": {"type": "string"}}, "required": ["capture_id"], "additionalProperties": False}},
        {"name": "personal_capture_user_turn", "description": "Before any derived records, save the user's full personal-understanding message verbatim. After capture the status is pending; derivation and finalize are still required. Cannot be overwritten or silently modified.", "inputSchema": {"type": "object", "properties": {"capture_id": {"type": "string"}, "text": {"type": "string"}, "conversation_id": {"type": "string"}, "captured_at": {"type": "string"}, "message_kind": {"type": "string"}}, "required": ["capture_id", "text"], "additionalProperties": False}},
        {"name": "personal_add_record", "description": "Create a derived record. If the source is a current user supplement, a verbatim capture must exist first and verbatim_refs must be written into the record.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "kind": {"type": "string", "enum": sorted(VALID_KINDS)}, "domain": {"type": "string"}, "summary": {"type": "string"}, "source_refs": {"type": "string"}, "verbatim_refs": {"type": "string"}, "capture_id": {"type": "string"}, "confidence": {"type": "string", "enum": sorted(VALID_CONFIDENCE), "default": "high"}, "sensitivity": {"type": "string", "enum": sorted(VALID_SENSITIVITY), "default": "ordinary"}, "related_ids": {"type": "string"}, "aliases": {"type": "string"}, "salience": {"type": "integer", "minimum": 0, "maximum": 3}, "phase": {"type": "string"}, "valid_from": {"type": ["string", "null"]}, "last_confirmed": {"type": ["string", "null"]}, "date_end": {"type": ["string", "null"]}, "date_precision": {"type": "string"}, "date_basis": {"type": "string"}, "entity_refs": {"type": "string"}, "record_role": {"type": "string"}}, "required": ["id", "kind", "summary"], "additionalProperties": False}},
        {"name": "personal_finalize_capture", "description": "Close the derivation closure of the current verbatim capture. derived must already have at least one bidirectionally linked record; when no derivation is needed, a concrete reason must be given. Must be called before answering.", "inputSchema": {"type": "object", "properties": {"capture_id": {"type": "string"}, "disposition": {"type": "string", "enum": ["derived", "no-derivation-needed"]}, "reason": {"type": "string"}}, "required": ["capture_id", "disposition"], "additionalProperties": False}},
        {"name": "personal_derivation_status", "description": "Read the capture→records closure status; check pending, orphaned captures, and link drift.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "personal_add_followup", "description": "Register a follow-up question with context; the personal-understanding skill proactively checks it once due.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "prompt": {"type": "string"}, "context": {"type": "string"}, "due_at": {"type": ["string", "null"]}, "due_rule": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}, "priority": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"}}, "required": ["id", "prompt", "context"], "additionalProperties": False}},
        {"name": "personal_add_hypothesis", "description": "Register a candidate causal explanation; defaults to candidate and must not pose as fact.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "claim": {"type": "string"}, "mechanism": {"type": "string"}, "supports": {"type": "array", "items": {"type": "string"}}, "contradicts": {"type": "array", "items": {"type": "string"}}, "alternatives": {"type": "array", "items": {"type": "string"}}, "scope": {"type": "string"}, "confidence": {"type": "string", "enum": sorted(VALID_CONFIDENCE), "default": "low"}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["id", "claim", "mechanism"], "additionalProperties": False}},
        {"name": "personal_validate", "description": "Validate v2 structure and clearly distinguish failures, warnings, and clean. By default requires all captures to have completed derivation closure. Read-only.", "inputSchema": {"type": "object", "properties": {"strict": {"type": "boolean", "default": False}}, "additionalProperties": False}},
        {"name": "personal_add_feedback", "description": "Record the outcome of an answer that leaned on personal memory: which memories were used and whether the user's reaction showed helpful/missed/corrected. No formal user rating required.", "inputSchema": {"type": "object", "properties": {"feedback_id": {"type": "string"}, "capture_id": {"type": "string"}, "memory_ids": {"type": "string"}, "outcome": {"type": "string", "enum": ["helpful", "missed", "corrected", "unclear"]}, "note": {"type": "string"}}, "required": ["feedback_id", "outcome"], "additionalProperties": False}},
        {"name": "personal_session_check", "description": "Hard gate before answering or claiming the archive was updated: structural validation + derivation closure + v2 integrity pass in one command. On failure, memory must not be claimed as updated.", "inputSchema": {"type": "object", "properties": {"allow_warnings": {"type": "boolean", "default": False}}, "additionalProperties": False}},
    ]


def capture(data: dict[str, Any]) -> dict[str, Any]:
    capture_id = str(data.get("capture_id", "")).strip(); text = data.get("text")
    if not ID_RE.fullmatch(capture_id): return text_result("Write refused: invalid capture_id.", error=True)
    if not isinstance(text, str): return text_result("Write refused: text must be a string.", error=True)
    CAPTURES.mkdir(parents=True, exist_ok=True); txt = CAPTURES / f"{capture_id}.txt"; meta_path = CAPTURES / f"{capture_id}.json"
    if txt.exists() or meta_path.exists(): return text_result("Refusing to overwrite an existing verbatim capture.", error=True)
    raw = text.encode("utf-8"); digest = hashlib.sha256(raw).hexdigest(); txt.write_bytes(raw)
    if txt.read_bytes() != raw:
        txt.unlink(missing_ok=True); return text_result("Verbatim read-back verification failed; the write was rolled back.", error=True)
    meta = {"capture_id": capture_id, "captured_at": str(data.get("captured_at") or dt.datetime.now().astimezone().isoformat(timespec="seconds")), "speaker": "user", "message_kind": str(data.get("message_kind") or "personal-understanding-update"), "conversation_id": data.get("conversation_id"), "byte_length": len(raw), "utf8_sha256": digest, "codepoint_length": len(text), "immutable": True, "source_path": txt.relative_to(ROOT).as_posix()}
    meta_tmp = meta_path.with_suffix(meta_path.suffix + ".tmp")
    meta_tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(meta_tmp, meta_path)
    register_capture(capture_id, source_path=meta["source_path"], captured_at=meta["captured_at"], message_kind=meta["message_kind"], content_sha256=digest, root=ROOT)
    code, output = rebuild_and_validate()
    result = {"status": "captured", "capture_id": capture_id, "source_path": meta["source_path"], "sha256": digest, "derivation_status": "pending", "view_rebuild_and_validation": output, "validation_code": code, "next_required_action": "add derived records, then call personal_finalize_capture"}
    return text_result(json.dumps(result, ensure_ascii=False, indent=2), error=code != 0)


def require_capture(data: dict[str, Any]) -> tuple[bool, str]:
    capture_id = str(data.get("capture_id", "")).strip()
    if not ID_RE.fullmatch(capture_id):
        return False, "Read refused: complete this turn's verbatim capture first and provide a valid capture_id."
    if capture_id not in discover_captures(ROOT):
        return False, f"Read refused: capture_id does not exist: {capture_id}. Save the verbatim text or attachment first."
    return True, ""


def join_list_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def add_record(data: dict[str, Any]) -> dict[str, Any]:
    record_id = str(data.get("id", "")).strip(); kind = str(data.get("kind", "")).strip(); summary = str(data.get("summary", "")).strip(); confidence = str(data.get("confidence", "high")).strip(); sensitivity = str(data.get("sensitivity", "ordinary")).strip(); domain = str(data.get("domain", "")).strip(); source_refs = [ref.strip() for ref in re.split(r"[;,]", str(data.get("source_refs", ""))) if ref.strip()]; verbatim_refs = [ref.strip() for ref in re.split(r"[;,]", str(data.get("verbatim_refs", ""))) if ref.strip()]; capture_id = str(data.get("capture_id", "")).strip()
    if not ID_RE.fullmatch(record_id): return text_result("Write refused: invalid id.", error=True)
    if kind not in VALID_KINDS or confidence not in VALID_CONFIDENCE or sensitivity not in VALID_SENSITIVITY: return text_result("Write refused: invalid kind / confidence / sensitivity.", error=True)
    if not summary: return text_result("Write refused: summary must not be empty.", error=True)
    if kind in {"state", "decision", "model", "value", "heuristic", "rule", "preference"} and not domain: return text_result(f"Write refused: kind {kind} requires a domain.", error=True)
    if capture_id:
        capture_meta = discover_captures(ROOT).get(capture_id)
        if not capture_meta: return text_result("Write refused: capture_id does not exist; save the verbatim text or attachment first.", error=True)
        source_path = str(capture_meta.get("source_path") or "").strip()
        if source_path: source_refs.append(source_path)
        verbatim_refs.append(f"fragment.capture.{capture_id}")
    if "current-conversation" in source_refs and not verbatim_refs: return text_result("Write refused: current-conversation cannot replace verbatim; provide capture_id or verbatim_refs.", error=True)
    path = RECORDS / f"{record_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): return text_result(f"Refusing to overwrite an existing record: {path.name}.", error=True)
    today = dt.date.today().isoformat(); valid_from = data.get("valid_from"); last_confirmed = data.get("last_confirmed") or today
    lines = ["---", f"id: {record_id}", f"kind: {kind}", "status: current", f"confidence: {confidence}", f"sensitivity: {sensitivity}"]
    if valid_from not in (None, ""): lines.append(f"valid_from: {valid_from}")
    if last_confirmed not in (None, ""): lines.append(f"last_confirmed: {last_confirmed}")
    if domain: lines.extend([f"domain: {domain}", f"parent_ids: {domain}"])
    for key in ("salience", "phase", "date_end", "date_precision", "date_basis", "entity_refs", "record_role"):
        value = join_list_value(data.get(key))
        if value not in (None, ""):
            lines.append(f"{key}: {value}")
    for key in ("related_ids", "aliases"):
        value = join_list_value(data.get(key))
        if value: lines.append(f"{key}: {value}")
    if source_refs: lines.append("source_refs: " + "; ".join(dict.fromkeys(source_refs)))
    if verbatim_refs: lines.append("verbatim_refs: " + "; ".join(dict.fromkeys(verbatim_refs)))
    lines.extend(["schema_version: 2.0.0", "---", "", summary, ""]); path.write_text("\n".join(lines), encoding="utf-8")
    linked_capture_ids = set()
    if capture_id: linked_capture_ids.add(capture_id)
    for ref in verbatim_refs:
        if ref.startswith("fragment.capture."): linked_capture_ids.add(ref.removeprefix("fragment.capture."))
    for linked_capture_id in linked_capture_ids:
        link_record(linked_capture_id, record_id, root=ROOT)
    code, output = rebuild_and_validate()
    return text_result(f"Created: {path.name}; linked captures: {', '.join(sorted(linked_capture_ids)) or 'none'}. The capture is still pending; finalize after finishing all splits for this turn.\n\n{output}", error=code != 0)



def finalize_capture_tool(data: dict[str, Any]) -> dict[str, Any]:
    capture_id = str(data.get("capture_id", "")).strip(); disposition = str(data.get("disposition", "")).strip(); reason = str(data.get("reason", "")).strip()
    try:
        entry = finalize_capture(capture_id, disposition, reason, root=ROOT)
    except ValueError as exc:
        return text_result(f"Refusing to close capture: {exc}", error=True)
    # finalize only updates the derivation ledger and touches no v2 derived views;
    # validation is enough, a full rebuild is unnecessary.
    code, output = run_script("validate_memory.py", ["--require-closed-captures"])
    return text_result(json.dumps({"status": "finalized", "capture": entry, "validation": output}, ensure_ascii=False, indent=2), error=code != 0)

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def add_followup(data: dict[str, Any]) -> dict[str, Any]:
    ident = str(data.get("id", "")).strip(); prompt = str(data.get("prompt", "")).strip(); context = str(data.get("context", "")).strip()
    if not ID_RE.fullmatch(ident) or not prompt or not context: return text_result("Write refused: followup id, prompt, and context are required and must be valid.", error=True)
    path = V2 / "followups.jsonl"
    rows = read_jsonl(path)
    if any(row.get("id") == ident for row in rows): return text_result("Refusing to overwrite an existing followup.", error=True)
    rows.append({"id": ident, "prompt": prompt, "context": context, "status": "pending", "due_at": data.get("due_at"), "due_rule": data.get("due_rule") or "next-relevant-activation", "source_refs": data.get("source_refs") or [], "created_at": dt.date.today().isoformat(), "last_checked_at": None, "snooze_until": None, "priority": data.get("priority") or "normal"})
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in sorted(rows, key=lambda row: row["id"]))
    write_text_atomic(path, payload)
    code, output = rebuild_and_validate(); return text_result(f"Follow-up registered: {ident}\n\n{output}", error=code != 0)


def add_hypothesis(data: dict[str, Any]) -> dict[str, Any]:
    ident = str(data.get("id", "")).strip(); claim = str(data.get("claim", "")).strip(); mechanism = str(data.get("mechanism", "")).strip()
    if not ID_RE.fullmatch(ident) or not claim or not mechanism: return text_result("Write refused: hypothesis id, claim, and mechanism are required and must be valid.", error=True)
    path = V2 / "hypotheses.jsonl"
    rows = read_jsonl(path)
    if any(row.get("id") == ident for row in rows): return text_result("Refusing to overwrite an existing hypothesis.", error=True)
    row = {"id": ident, "kind": "causal_hypothesis", "status": "candidate", "claim": claim, "mechanism": mechanism, "supports": data.get("supports") or [], "contradicts": data.get("contradicts") or [], "alternatives": data.get("alternatives") or [], "scope": data.get("scope") or "", "confidence": data.get("confidence") or "low", "source_refs": data.get("source_refs") or [], "created_at": dt.date.today().isoformat(), "last_reviewed_at": None}
    rows.append(row)
    payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in sorted(rows, key=lambda item: item["id"]))
    write_text_atomic(path, payload)
    code, output = rebuild_and_validate(); return text_result(f"Candidate causal hypothesis registered: {ident}\n\n{output}", error=code != 0)


UNKNOWN_METHOD = object()


def handle(method: str, params: dict[str, Any]) -> Any:
    if method == "initialize": return {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}, "resources": {}}, "serverInfo": {"name": "personal-understanding", "version": skill_version()}, "instructions": "This is the local personal-understanding v2 MCP. Save user supplements verbatim first, then create derived records."}
    if method == "tools/list": return {"tools": tool_definitions()}
    if method == "resources/list": return {"resources": [{"uri": "personal://catalog/survey", "name": "Personal understanding v2 global survey", "mimeType": "application/json", "description": "Timeline spine, entities, contexts, current state, and follow-ups."}, {"uri": "personal://skill/info", "name": "Personal understanding skill info", "mimeType": "text/markdown", "description": "v2 rules and entry points."}]}
    if method == "resources/read":
        uri = str(params.get("uri", ""))
        if uri == "personal://catalog/survey":
            code, output = run_script("catalog_context.py", ["--view", "survey"]); return {"contents": [{"uri": uri, "mimeType": "application/json", "text": output}]} if not code else (_ for _ in ()).throw(RuntimeError(output))
        if uri == "personal://skill/info": return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": (ROOT / "SKILL.md").read_text(encoding="utf-8")}]} 
        raise ValueError(f"Unknown resource: {uri}")
    if method == "tools/call":
        name = str(params.get("name", "")); args = params.get("arguments", {})
        if not isinstance(args, dict): return text_result("arguments must be an object.", error=True)
        if name == "personal_catalog":
            ok, message = require_capture(args)
            if not ok: return text_result(message, error=True)
            view = str(args.get("view", "survey"));
            if view not in {"survey", "routing", "full"}: return text_result("Invalid view.", error=True)
            cmd = ["--view", view];
            if args.get("query"): cmd += ["--query", str(args["query"])]
            code, output = run_script("catalog_context.py", cmd); return text_result(output, error=bool(code))
        if name == "personal_retrieve":
            ok, message = require_capture(args)
            if not ok: return text_result(message, error=True)
            ids = args.get("ids") or []; query = str(args.get("query", "")); level = str(args.get("level", "probe")); cmd = ["--level", level]
            if ids: cmd += ["--event-ids", ",".join(str(item) for item in ids), "--entity-ids", ",".join(str(item) for item in ids)]
            if query: cmd += ["--query", query]
            code, output = run_script("retrieve_v2.py", cmd); return text_result(output, error=bool(code))
        if name == "personal_capture_user_turn": return capture(args)
        if name == "personal_add_record": return add_record(args)
        if name == "personal_finalize_capture": return finalize_capture_tool(args)
        if name == "personal_derivation_status": return text_result(json.dumps(audit_ledger(ROOT), ensure_ascii=False, indent=2))
        if name == "personal_add_followup": return add_followup(args)
        if name == "personal_add_hypothesis": return add_hypothesis(args)
        if name == "personal_add_feedback":
            cmd = ["--feedback-id", str(args.get("feedback_id", "")), "--outcome", str(args.get("outcome", ""))]
            if args.get("capture_id"): cmd += ["--capture-id", str(args["capture_id"])]
            if args.get("memory_ids"): cmd += ["--memory-ids", str(args["memory_ids"])]
            if args.get("note"): cmd += ["--note", str(args["note"])]
            code, output = run_script("record_feedback.py", cmd); return text_result(output, error=bool(code))
        if name == "personal_session_check":
            cmd = ["session_check.py"] + (["--allow-warnings"] if args.get("allow_warnings") else [])
            code, output = run_script(cmd[0], cmd[1:]); return text_result(output, error=bool(code))
        if name == "personal_validate":
            cmd = ["--json", "--require-closed-captures"] + (["--strict"] if args.get("strict") else []); code, output = run_script("validate_memory.py", cmd); return text_result(output, error=bool(code))
        return text_result(f"Unknown tool: {name}", error=True)
    return UNKNOWN_METHOD


def main() -> None:
    for raw in sys.stdin:
        msg = None
        try:
            msg = json.loads(raw); method = msg.get("method")
            if not method: continue
            result = handle(str(method), msg.get("params") or {})
            if result is UNKNOWN_METHOD:
                if "id" in msg:
                    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"Unknown method: {method}"}}, ensure_ascii=False), flush=True)
                continue
            if "id" in msg: print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}, ensure_ascii=False), flush=True)
        except Exception as exc:
            if isinstance(msg, dict) and "id" in msg: print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(exc)}}, ensure_ascii=False), flush=True)


if __name__ == "__main__": main()
