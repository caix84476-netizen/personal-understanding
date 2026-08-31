#!/usr/bin/env python3
"""Local-only MCP server for personal-understanding v2."""
from __future__ import annotations
import datetime as dt
import hashlib, json, os, re, subprocess, sys
from pathlib import Path
from typing import Any
from derivation_ledger import audit_ledger, discover_captures, finalize_capture, link_record, register_capture
from v2_archive import skill_version, write_text_atomic
from storage import atomic_write_bytes, atomic_write_text, mutation_lock
from turn_receipts import create_receipt, mark_captured, read_receipt

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
        {"name": "personal_preflight_turn", "description": "当前用户消息的强制内容预检。它持久化 turn receipt；个人经历、感受、关系、偏好、决定即使请求形式是润色/总结/看图，也会要求 capture。", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "turn_id": {"type": "string"}, "conversation_id": {"type": "string"}}, "required": ["text"], "additionalProperties": False}},
        {"name": "personal_catalog", "description": "读取 v2 全局勘察。必须先完成当前轮次 turn preflight capture，并提供 capture_id；否则拒绝读取。", "inputSchema": {"type": "object", "properties": {"view": {"type": "string", "enum": ["survey", "routing", "full"], "default": "survey"}, "query": {"type": "string"}, "capture_id": {"type": "string"}}, "required": ["capture_id"], "additionalProperties": False}},
        {"name": "personal_retrieve", "description": "按 v2 事件、实体和情境卡读取 probe/deep。必须先完成当前轮次 turn preflight capture，并提供 capture_id；否则拒绝读取。", "inputSchema": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}}, "level": {"type": "string", "enum": ["probe", "deep"], "default": "probe"}, "query": {"type": "string"}, "capture_id": {"type": "string"}}, "required": ["capture_id"], "additionalProperties": False}},
        {"name": "personal_capture_user_turn", "description": "绑定已判定为个人材料的 turn receipt，原样保存完整用户消息。没有 preflight 或 preflight 判为非个人时拒绝写入；捕获后仍必须派生并 finalize。", "inputSchema": {"type": "object", "properties": {"capture_id": {"type": "string"}, "turn_id": {"type": "string"}, "text": {"type": "string"}, "conversation_id": {"type": "string"}, "captured_at": {"type": "string"}, "message_kind": {"type": "string"}}, "required": ["capture_id", "turn_id", "text"], "additionalProperties": False}},
        {"name": "personal_add_record", "description": "创建派生记录。若来源是当前用户补充，必须先有 verbatim capture，并把 verbatim_refs 写入记录。", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "kind": {"type": "string", "enum": sorted(VALID_KINDS)}, "domain": {"type": "string"}, "summary": {"type": "string"}, "source_refs": {"type": "string"}, "verbatim_refs": {"type": "string"}, "capture_id": {"type": "string"}, "confidence": {"type": "string", "enum": sorted(VALID_CONFIDENCE), "default": "high"}, "sensitivity": {"type": "string", "enum": sorted(VALID_SENSITIVITY), "default": "ordinary"}, "related_ids": {"type": "string"}, "aliases": {"type": "string"}, "salience": {"type": "integer", "minimum": 0, "maximum": 3}, "phase": {"type": "string"}, "valid_from": {"type": ["string", "null"]}, "last_confirmed": {"type": ["string", "null"]}, "date_end": {"type": ["string", "null"]}, "date_precision": {"type": "string"}, "date_basis": {"type": "string"}, "entity_refs": {"type": "string"}, "record_role": {"type": "string"}}, "required": ["id", "kind", "summary"], "additionalProperties": False}},
        {"name": "personal_finalize_capture", "description": "关闭当前原话捕获的派生闭环。derived 必须已有至少一条双向链接记录；无需派生时必须写具体原因。回答前必须调用。", "inputSchema": {"type": "object", "properties": {"capture_id": {"type": "string"}, "disposition": {"type": "string", "enum": ["derived", "no-derivation-needed"]}, "reason": {"type": "string"}}, "required": ["capture_id", "disposition"], "additionalProperties": False}},
        {"name": "personal_derivation_status", "description": "读取 capture→records 闭环状态，检查 pending、孤立捕获和链接漂移。", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "personal_add_followup", "description": "登记有上下文的待回访问题；到期后由个人理解 Skill 主动检查。", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "prompt": {"type": "string"}, "context": {"type": "string"}, "due_at": {"type": ["string", "null"]}, "due_rule": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}, "priority": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"}}, "required": ["id", "prompt", "context"], "additionalProperties": False}},
        {"name": "personal_add_hypothesis", "description": "登记候选因果解释；默认 candidate，不得冒充事实。", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "claim": {"type": "string"}, "mechanism": {"type": "string"}, "supports": {"type": "array", "items": {"type": "string"}}, "contradicts": {"type": "array", "items": {"type": "string"}}, "alternatives": {"type": "array", "items": {"type": "string"}}, "scope": {"type": "string"}, "confidence": {"type": "string", "enum": sorted(VALID_CONFIDENCE), "default": "low"}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["id", "claim", "mechanism"], "additionalProperties": False}},
        {"name": "personal_validate", "description": "校验 v2 结构，并明确区分失败、警告和干净。默认强制要求所有 capture 已完成派生闭环。只读。", "inputSchema": {"type": "object", "properties": {"strict": {"type": "boolean", "default": False}}, "additionalProperties": False}},
        {"name": "personal_add_feedback", "description": "记录一次依赖个人记忆的回答的效果：用了哪些记忆、用户反应说明 helpful/missed/corrected。不需要用户正式打分。", "inputSchema": {"type": "object", "properties": {"feedback_id": {"type": "string"}, "capture_id": {"type": "string"}, "memory_ids": {"type": "string"}, "outcome": {"type": "string", "enum": ["helpful", "missed", "corrected", "unclear"]}, "note": {"type": "string"}}, "required": ["feedback_id", "outcome"], "additionalProperties": False}},
        {"name": "personal_session_check", "description": "回答或声称档案已更新前的硬闸门：turn receipt + capture 闭环 + 结构 + v2 完整性。个人 turn 必须传 turn_id，缺 capture 或 finalize 会失败。", "inputSchema": {"type": "object", "properties": {"turn_id": {"type": "string"}, "allow_warnings": {"type": "boolean", "default": False}}, "additionalProperties": False}},
    ]


def capture(data: dict[str, Any]) -> dict[str, Any]:
    capture_id = str(data.get("capture_id", "")).strip(); turn_id = str(data.get("turn_id", "")).strip(); text = data.get("text")
    if not ID_RE.fullmatch(capture_id): return text_result("拒绝写入：capture_id 不合法。", error=True)
    if not ID_RE.fullmatch(turn_id): return text_result("拒绝写入：必须先运行 personal_preflight_turn，并提供合法 turn_id。", error=True)
    if not isinstance(text, str): return text_result("拒绝写入：text 必须是字符串。", error=True)
    raw = text.encode("utf-8"); digest = hashlib.sha256(raw).hexdigest(); txt = CAPTURES / f"{capture_id}.txt"; meta_path = CAPTURES / f"{capture_id}.json"
    meta = {"capture_id": capture_id, "captured_at": str(data.get("captured_at") or dt.datetime.now().astimezone().isoformat(timespec="seconds")), "speaker": "user", "message_kind": str(data.get("message_kind") or "personal-understanding-update"), "conversation_id": data.get("conversation_id"), "byte_length": len(raw), "utf8_sha256": digest, "codepoint_length": len(text), "immutable": True, "source_path": txt.relative_to(ROOT).as_posix()}
    try:
        with mutation_lock(ROOT):
            receipt = read_receipt(turn_id, ROOT)
            if not receipt or not receipt.get("requires_personal_understanding"): return text_result("拒绝写入：turn receipt 不存在或未判为个人材料。", error=True)
            if receipt.get("message_sha256") != digest: return text_result("拒绝写入：capture 文本与 preflight 的完整用户消息不一致。", error=True)
            if txt.exists() or meta_path.exists(): return text_result("拒绝覆盖已有原话捕获。", error=True)
            atomic_write_bytes(txt, raw)
            if txt.read_bytes() != raw: raise RuntimeError("原话回读校验失败")
            atomic_write_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
            register_capture(capture_id, source_path=meta["source_path"], captured_at=meta["captured_at"], message_kind=meta["message_kind"], content_sha256=digest, root=ROOT)
            mark_captured(turn_id, capture_id, ROOT)
    except Exception as exc:
        meta_path.unlink(missing_ok=True); txt.unlink(missing_ok=True)
        return text_result(f"原话捕获失败，已撤销未完成文件：{exc}", error=True)
    code, output = rebuild_and_validate()
    result = {"status": "captured", "capture_id": capture_id, "turn_id": turn_id, "source_path": meta["source_path"], "sha256": digest, "derivation_status": "pending", "view_rebuild_and_validation": output, "validation_code": code, "next_required_action": "add derived records, then call personal_finalize_capture"}
    return text_result(json.dumps(result, ensure_ascii=False, indent=2), error=code != 0)


def require_capture(data: dict[str, Any]) -> tuple[bool, str]:
    capture_id = str(data.get("capture_id", "")).strip()
    if not ID_RE.fullmatch(capture_id):
        return False, "拒绝读取：必须先完成当前轮次原话捕获，并提供合法 capture_id。"
    if capture_id not in discover_captures(ROOT):
        return False, f"拒绝读取：capture_id 不存在：{capture_id}。先保存原话或附件。"
    return True, ""


def join_list_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def add_record(data: dict[str, Any]) -> dict[str, Any]:
    record_id = str(data.get("id", "")).strip(); kind = str(data.get("kind", "")).strip(); summary = str(data.get("summary", "")).strip(); confidence = str(data.get("confidence", "high")).strip(); sensitivity = str(data.get("sensitivity", "ordinary")).strip(); domain = str(data.get("domain", "")).strip(); source_refs = [ref.strip() for ref in re.split(r"[;,]", str(data.get("source_refs", ""))) if ref.strip()]; verbatim_refs = [ref.strip() for ref in re.split(r"[;,]", str(data.get("verbatim_refs", ""))) if ref.strip()]; capture_id = str(data.get("capture_id", "")).strip()
    if not ID_RE.fullmatch(record_id): return text_result("拒绝写入：id 不合法。", error=True)
    if kind not in VALID_KINDS or confidence not in VALID_CONFIDENCE or sensitivity not in VALID_SENSITIVITY: return text_result("拒绝写入：kind / confidence / sensitivity 不合法。", error=True)
    if not summary: return text_result("拒绝写入：summary 不能为空。", error=True)
    if kind in {"state", "decision", "model", "value", "heuristic", "rule", "preference"} and not domain: return text_result(f"拒绝写入：{kind} 类型必须提供 domain。", error=True)
    if capture_id:
        capture_meta = discover_captures(ROOT).get(capture_id)
        if not capture_meta: return text_result("拒绝写入：capture_id 不存在；先保存原话或附件。", error=True)
        source_path = str(capture_meta.get("source_path") or "").strip()
        if source_path: source_refs.append(source_path)
        verbatim_refs.append(f"fragment.capture.{capture_id}")
    if "current-conversation" in source_refs and not verbatim_refs: return text_result("拒绝写入：current-conversation 不能代替原话；必须提供 capture_id 或 verbatim_refs。", error=True)
    path = RECORDS / f"{record_id}.md"
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
    lines.extend(["schema_version: 2.0.0", "---", "", summary, ""])
    linked_capture_ids = set()
    if capture_id: linked_capture_ids.add(capture_id)
    for ref in verbatim_refs:
        if ref.startswith("fragment.capture."): linked_capture_ids.add(ref.removeprefix("fragment.capture."))
    with mutation_lock(ROOT):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists(): return text_result(f"拒绝覆盖已有记录：{path.name}。", error=True)
        atomic_write_text(path, "\n".join(lines))
        for linked_capture_id in linked_capture_ids:
            link_record(linked_capture_id, record_id, root=ROOT)
    code, output = rebuild_and_validate()
    return text_result(f"已创建：{path.name}；关联 capture：{', '.join(sorted(linked_capture_ids)) or '无'}。capture 仍为 pending，完成本轮全部拆分后必须 finalize。\n\n{output}", error=code != 0)



def finalize_capture_tool(data: dict[str, Any]) -> dict[str, Any]:
    capture_id = str(data.get("capture_id", "")).strip(); disposition = str(data.get("disposition", "")).strip(); reason = str(data.get("reason", "")).strip()
    try:
        entry = finalize_capture(capture_id, disposition, reason, root=ROOT)
    except ValueError as exc:
        return text_result(f"拒绝关闭 capture：{exc}", error=True)
    # finalize 只改派生台账，不影响任何 v2 派生视图；只需校验，不必全量重建。
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
    if not ID_RE.fullmatch(ident) or not prompt or not context: return text_result("拒绝写入：followup id、prompt、context 必填且合法。", error=True)
    path = V2 / "followups.jsonl"
    with mutation_lock(ROOT):
        rows = read_jsonl(path)
        if any(row.get("id") == ident for row in rows): return text_result("拒绝覆盖已有 followup。", error=True)
        rows.append({"id": ident, "prompt": prompt, "context": context, "status": "pending", "due_at": data.get("due_at"), "due_rule": data.get("due_rule") or "next-relevant-activation", "source_refs": data.get("source_refs") or [], "created_at": dt.date.today().isoformat(), "last_checked_at": None, "snooze_until": None, "priority": data.get("priority") or "normal"})
        payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in sorted(rows, key=lambda row: row["id"]))
        write_text_atomic(path, payload)
    code, output = rebuild_and_validate(); return text_result(f"已登记待回访：{ident}\n\n{output}", error=code != 0)


def add_hypothesis(data: dict[str, Any]) -> dict[str, Any]:
    ident = str(data.get("id", "")).strip(); claim = str(data.get("claim", "")).strip(); mechanism = str(data.get("mechanism", "")).strip()
    if not ID_RE.fullmatch(ident) or not claim or not mechanism: return text_result("拒绝写入：hypothesis id、claim、mechanism 必填且合法。", error=True)
    path = V2 / "hypotheses.jsonl"
    with mutation_lock(ROOT):
        rows = read_jsonl(path)
        if any(row.get("id") == ident for row in rows): return text_result("拒绝覆盖已有 hypothesis。", error=True)
        row = {"id": ident, "kind": "causal_hypothesis", "status": "candidate", "claim": claim, "mechanism": mechanism, "supports": data.get("supports") or [], "contradicts": data.get("contradicts") or [], "alternatives": data.get("alternatives") or [], "scope": data.get("scope") or "", "confidence": data.get("confidence") or "low", "source_refs": data.get("source_refs") or [], "created_at": dt.date.today().isoformat(), "last_reviewed_at": None}
        rows.append(row)
        payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in sorted(rows, key=lambda item: item["id"]))
        write_text_atomic(path, payload)
    code, output = rebuild_and_validate(); return text_result(f"已登记候选因果假设：{ident}\n\n{output}", error=code != 0)


UNKNOWN_METHOD = object()


def handle(method: str, params: dict[str, Any]) -> Any:
    if method == "initialize": return {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}, "resources": {}}, "serverInfo": {"name": "personal-understanding", "version": skill_version()}, "instructions": "这是本地个人理解 v2 MCP。个人补充必须先保存原话，再生成派生档案。"}
    if method == "tools/list": return {"tools": tool_definitions()}
    if method == "resources/list": return {"resources": [{"uri": "personal://catalog/survey", "name": "个人理解 v2 全局勘察", "mimeType": "application/json", "description": "时间主干、实体、情境、当前状态和待回访。"}, {"uri": "personal://skill/info", "name": "个人理解 Skill 信息", "mimeType": "text/markdown", "description": "v2 规则和入口。"}]}
    if method == "resources/read":
        uri = str(params.get("uri", ""))
        if uri == "personal://catalog/survey":
            code, output = run_script("catalog_context.py", ["--view", "survey"]); return {"contents": [{"uri": uri, "mimeType": "application/json", "text": output}]} if not code else (_ for _ in ()).throw(RuntimeError(output))
        if uri == "personal://skill/info": return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": (ROOT / "SKILL.md").read_text(encoding="utf-8")}]} 
        raise ValueError(f"未知资源：{uri}")
    if method == "tools/call":
        name = str(params.get("name", "")); args = params.get("arguments", {})
        if not isinstance(args, dict): return text_result("arguments 必须是对象。", error=True)
        if name == "personal_preflight_turn":
            text = args.get("text")
            if not isinstance(text, str): return text_result("text 必须是字符串。", error=True)
            try:
                receipt = create_receipt(text, turn_id=str(args.get("turn_id") or "") or None, conversation_id=str(args.get("conversation_id") or "") or None, root=ROOT)
            except ValueError as exc: return text_result(f"preflight 失败：{exc}", error=True)
            return text_result(json.dumps(receipt, ensure_ascii=False, indent=2))
        if name == "personal_catalog":
            ok, message = require_capture(args)
            if not ok: return text_result(message, error=True)
            view = str(args.get("view", "survey"));
            if view not in {"survey", "routing", "full"}: return text_result("view 不合法。", error=True)
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
            cmd = ["session_check.py"] + (["--turn-id", str(args["turn_id"])] if args.get("turn_id") else []) + (["--allow-warnings"] if args.get("allow_warnings") else [])
            code, output = run_script(cmd[0], cmd[1:]); return text_result(output, error=bool(code))
        if name == "personal_validate":
            cmd = ["--json", "--require-closed-captures"] + (["--strict"] if args.get("strict") else []); code, output = run_script("validate_memory.py", cmd); return text_result(output, error=bool(code))
        return text_result(f"未知工具：{name}", error=True)
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
                    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"未知方法：{method}"}}, ensure_ascii=False), flush=True)
                continue
            if "id" in msg: print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}, ensure_ascii=False), flush=True)
        except Exception as exc:
            if isinstance(msg, dict) and "id" in msg: print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(exc)}}, ensure_ascii=False), flush=True)


if __name__ == "__main__": main()
