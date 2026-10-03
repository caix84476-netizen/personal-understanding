#!/usr/bin/env python3
"""Local-only MCP server for personal-understanding v2."""
from __future__ import annotations
import datetime as dt
import hashlib, json, os, re, subprocess, sys
from pathlib import Path
from typing import Any
from derivation_ledger import audit_ledger, discover_captures, finalize_capture, link_record, load_ledger, register_capture, repair_ledger
from v2_archive import loose_followup_fields, resolve_followup, skill_version, write_text_atomic
from storage import atomic_write_bytes, atomic_write_text, mutation_lock
from turn_receipts import create_receipt, mark_captured, read_receipt
from followup_check import check_followups
from schema import DATE_FORMAT_HINT, VALID_CONFIDENCE, VALID_KINDS, VALID_SENSITIVITY, branch_ids, valid_date_string
from view_freshness import ensure_fresh_views
from cli_runtime import configure_utf8_stdio

# MCP frames are UTF-8 JSON-RPC by spec; never trust the console code page (GBK/cp1252).
configure_utf8_stdio()

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RECORDS = ROOT / "memory" / "records"
V2 = ROOT / "memory" / "v2"
CAPTURES = ROOT / "sources" / "conversation"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
MAX_RESPONSE_CHARS = 200_000


def text_result(text: str, *, error: bool = False) -> dict[str, Any]:
    # Last-resort guard (2.7.0): a single MCP response must stay ingestible by a
    # model. View budgeting keeps normal responses far below this; the guard only
    # fires when something unbounded slipped through, and says so out loud.
    if len(text) > MAX_RESPONSE_CHARS:
        text = text[:MAX_RESPONSE_CHARS] + f"\n\n[响应已截断：原始 {len(text)} 字符超过 {MAX_RESPONSE_CHARS} 上限；请用更窄的 view/query/level 参数重试。]"
    return {"content": [{"type": "text", "text": text}], "isError": error}


def run_script(name: str, args: list[str]) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(SCRIPTS / name), *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    output = (proc.stdout + ("\n" if proc.stdout and proc.stderr else "") + proc.stderr).strip()
    return proc.returncode, output


def fresh_views_or_refuse() -> str | None:
    """Read tools rebuild stale views before serving (2.7.0). Write tools no
    longer rebuild inline: a full rebuild per write cost ~6s per turn and let
    the post-write validate race concurrent writers, reporting *successful*
    writes as failures. Staleness is mtime-based (view_freshness) — no flag
    file to strand after a crash. A failed rebuild refuses the read honestly:
    data is intact, the projection is just old."""
    try:
        ensure_fresh_views(ROOT, run_script)
    except RuntimeError as exc:
        return str(exc)
    return None


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {"name": "personal_preflight_turn", "description": "每轮入口：内容预检并持久化 turn receipt，判定本轮是否需要走个人档案流程（tier=auto/full/skip；light 已废弃按 full 处理）。个人材料轮此工具必须先于一切档案读写。", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "turn_id": {"type": "string"}, "conversation_id": {"type": "string"}, "tier": {"type": "string", "enum": ["auto", "full", "light", "skip"], "description": "auto=纯内容分类；full=完整档兜底；skip=强制跳过；light 已废弃按 full 处理"}}, "required": ["text"], "additionalProperties": False}},
        {"name": "personal_catalog", "description": "全局勘察：survey（紧凑路由地图）/ routing（按领域展开）/ full（完整目录）。交互读取须先完成本轮 capture 并传 capture_id；maintenance=true 为审计只读降级。预算 survey 48K / routing 68K / full 96K 字符。", "inputSchema": {"type": "object", "properties": {"view": {"type": "string", "enum": ["survey", "routing", "full"], "default": "survey"}, "query": {"type": "string"}, "domain": {"type": "string", "description": "按 branch id 过滤（routing/full 有效）"}, "max_chars": {"type": "integer"}, "capture_id": {"type": "string"}, "maintenance": {"type": "boolean", "default": False}}, "required": [], "additionalProperties": False}},
        {"name": "personal_retrieve", "description": "probe（按事件/实体/情境卡发散读派生卡片，80K 预算）/ deep（对选中条目读原话核验，100K 预算）。交互读取须先完成本轮 capture 并传 capture_id；maintenance=true 为审计只读降级。", "inputSchema": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}}, "level": {"type": "string", "enum": ["probe", "deep"], "default": "probe"}, "query": {"type": "string"}, "max_chars": {"type": "integer"}, "capture_id": {"type": "string"}, "maintenance": {"type": "boolean", "default": False}}, "required": [], "additionalProperties": False}},
        {"name": "personal_capture_user_turn", "description": "原样保存完整用户消息（不可变原话），绑定本轮 preflight receipt。没有 receipt 或 receipt 判非个人时拒绝写入；捕获后仍须派生并 finalize。", "inputSchema": {"type": "object", "properties": {"capture_id": {"type": "string"}, "turn_id": {"type": "string"}, "text": {"type": "string"}, "conversation_id": {"type": "string"}, "captured_at": {"type": "string"}, "message_kind": {"type": "string"}}, "required": ["capture_id", "turn_id", "text"], "additionalProperties": False}},
        {"name": "personal_add_record", "description": "创建派生记录。来源是用户补充时必须先有 capture 并带 capture_id/verbatim_refs；禁止裸 current-conversation。足迹微型记录传 tier=light（salience 0-1）。因果假设用 kind=causal_hypothesis，summary 写 'claim || mechanism'。", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "kind": {"type": "string", "enum": sorted(VALID_KINDS) + ["causal_hypothesis"]}, "domain": {"type": "string"}, "summary": {"type": "string"}, "tier": {"type": "string", "enum": ["full", "light"], "description": "记录形态：light=足迹微型记录（salience 0-1）；缺省 full。仅形态，非调用档位"}, "source_refs": {"type": "string"}, "verbatim_refs": {"type": "string"}, "capture_id": {"type": "string"}, "confidence": {"type": "string", "enum": sorted(VALID_CONFIDENCE), "default": "high"}, "sensitivity": {"type": "string", "enum": sorted(VALID_SENSITIVITY), "default": "ordinary"}, "related_ids": {"type": "string"}, "aliases": {"type": "string"}, "salience": {"type": "integer", "minimum": 0, "maximum": 3}, "phase": {"type": "string"}, "valid_from": {"type": ["string", "null"]}, "last_confirmed": {"type": ["string", "null"]}, "date_end": {"type": ["string", "null"]}, "date_precision": {"type": "string"}, "date_basis": {"type": "string"}, "entity_refs": {"type": "string"}, "record_role": {"type": "string"}}, "required": ["id", "kind", "summary"], "additionalProperties": False}},
        {"name": "personal_finalize_capture", "description": "关闭一条 capture 的派生闭环：derived（须已有至少一条双向链接记录）或 no-derivation-needed（须写明查重命中的具体记录）。回答前必须逐条关闭。", "inputSchema": {"type": "object", "properties": {"capture_id": {"type": "string"}, "disposition": {"type": "string", "enum": ["derived", "no-derivation-needed"]}, "reason": {"type": "string"}}, "required": ["capture_id", "disposition"], "additionalProperties": False}},
        {"name": "personal_add_followup", "description": "登记带上下文的待回访；到期后 Skill 主动检查。due_at 须为合法日历日期，相对说法换算成具体日期，不想定死就只写 due_rule。", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "prompt": {"type": "string"}, "context": {"type": "string"}, "due_at": {"type": ["string", "null"]}, "due_rule": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}, "priority": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"}}, "required": ["id", "prompt", "context"], "additionalProperties": False}},
        {"name": "personal_resolve_followup", "description": "关闭回访：answered（用户回复了）/ declined（不再跟进）/ resolved（被取代或过时）；note 必填且具体。用户回答是新原话时先 capture 再传 capture_id 绑定。", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "resolution": {"type": "string", "enum": ["answered", "declined", "resolved"]}, "note": {"type": "string"}, "capture_id": {"type": "string"}}, "required": ["id", "resolution", "note"], "additionalProperties": False}},
        {"name": "personal_add_feedback", "description": "记录一次依赖个人记忆的回答效果：outcome=helpful/missed/corrected/unclear，附用了哪些记忆与用户反应证据。", "inputSchema": {"type": "object", "properties": {"feedback_id": {"type": "string"}, "capture_id": {"type": "string"}, "memory_ids": {"type": "string"}, "outcome": {"type": "string", "enum": ["helpful", "missed", "corrected", "unclear"]}, "note": {"type": "string"}}, "required": ["feedback_id", "outcome"], "additionalProperties": False}},
        {"name": "personal_session_check", "description": "回答/声称档案已更新前的硬闸门。默认 light 模式（本轮 receipt+闭环+回访调度，毫秒级）；light=false 恢复全库结构校验（维护轮用）。个人轮必须传 turn_id；缺省自动审计最近 receipt。", "inputSchema": {"type": "object", "properties": {"turn_id": {"type": "string"}, "allow_warnings": {"type": "boolean", "default": False}, "stale_days": {"type": "integer", "default": 7}, "light": {"type": "boolean", "default": True, "description": "默认 true：只查本轮闸门；false=含全库 validate 的完整闸门"}}, "additionalProperties": False}},
        {"name": "personal_validate", "description": "全库结构校验（clean/warnings/failed 三态），并内嵌 capture→records 派生闭环审计（derivation=embed，吸收原 personal_derivation_status）。维护轮/迁移验收用；只读。", "inputSchema": {"type": "object", "properties": {"strict": {"type": "boolean", "default": False}, "derivation": {"type": "boolean", "default": True, "description": "内嵌派生台账审计（pending/孤立捕获/链接漂移）"}}, "additionalProperties": False}},
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
    # 2.7.0: isError now answers exactly one question — "did THIS write land?" —
    # verified by targeted checks (file read-back happened inside the lock; here
    # the ledger side). Inline rebuild+validate bundling is gone: under
    # concurrency the validate subprocess raced other writers and reported
    # successful captures as failures, which coerced blind retries and duplicate
    # ids. View freshness is the read path's job (fresh_views_or_refuse); the
    # whole-turn gate stays in session_check.
    registered = discover_captures(ROOT).get(capture_id)
    ledger_ok = bool(load_ledger(ROOT).get(capture_id))
    if not registered or not ledger_ok:
        return text_result(f"原话捕获失败：文件已写入但台账落位缺失（discover_captures={bool(registered)}，ledger={ledger_ok}）。不要用同一 capture_id 重试；先运行 personal_derivation_status 检查。", error=True)
    result = {"status": "captured", "capture_id": capture_id, "turn_id": turn_id, "source_path": meta["source_path"], "sha256": digest, "derivation_status": "pending", "view_rebuild": "deferred（下次读取自动重建，2.7.0 起写入不再内联重建）", "next_required_action": "add derived records, then call personal_finalize_capture"}
    return text_result(json.dumps(result, ensure_ascii=False, indent=2))


def require_capture(data: dict[str, Any]) -> tuple[bool, str]:
    capture_id = str(data.get("capture_id", "")).strip()
    if not ID_RE.fullmatch(capture_id):
        return False, "拒绝读取：必须先完成当前轮次原话捕获，并提供合法 capture_id。"
    if capture_id not in discover_captures(ROOT):
        return False, f"拒绝读取：capture_id 不存在：{capture_id}。先保存原话或附件。"
    return True, ""


def read_gate(data: dict[str, Any]) -> tuple[bool, str, bool]:
    """Read-side gate shared by catalog/retrieve (2.6.0).

    Normal interactive reads still demand this turn's capture. A read may pass
    WITHOUT a capture only via the explicit maintenance declaration — the same
    audited escape hatch as CLI --maintenance — because the fail-closed chain
    (footprint query judged non-personal -> rejected capture -> rejected read)
    was measured on 2026-09-05 to lock strategy/footprint turns out of *reading*
    entirely, and a read cannot corrupt the archive. Writes keep the hard gate."""
    if bool(data.get("maintenance")):
        return True, "", True
    ok, message = require_capture(data)
    return ok, message, False


def join_list_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def add_record(data: dict[str, Any]) -> dict[str, Any]:
    record_id = str(data.get("id", "")).strip(); kind = str(data.get("kind", "")).strip(); summary = str(data.get("summary", "")).strip(); confidence = str(data.get("confidence", "high")).strip(); sensitivity = str(data.get("sensitivity", "ordinary")).strip(); domain = str(data.get("domain", "")).strip(); tier = str(data.get("tier", "")).strip() or "full"; source_refs = [ref.strip() for ref in re.split(r"[;,]", str(data.get("source_refs", ""))) if ref.strip()]; verbatim_refs = [ref.strip() for ref in re.split(r"[;,]", str(data.get("verbatim_refs", ""))) if ref.strip()]; capture_id = str(data.get("capture_id", "")).strip()
    if not ID_RE.fullmatch(record_id): return text_result("拒绝写入：id 不合法。", error=True)
    # 2.8.0 瘦身：kind=causal_hypothesis 是 add_record 的专用伪 kind（不进 VALID_KINDS，
    # 避免 md 记录路径/validate_memory 接受它），在此先拦截路由到 hypotheses.jsonl。
    if kind == "causal_hypothesis":
        parts = [part.strip() for part in summary.split(" || ", 1)]
        if not ID_RE.fullmatch(record_id): return text_result("拒绝写入：id 不合法。", error=True)
        if len(parts) != 2 or not all(parts): return text_result("拒绝写入：kind=causal_hypothesis 的 summary 必须是 'claim || mechanism'（以 ' || ' 分隔）。", error=True)
        hyp_confidence = confidence or "low"
        if hyp_confidence not in VALID_CONFIDENCE: return text_result(f"拒绝写入：confidence 必须是 {'/'.join(sorted(VALID_CONFIDENCE))}，收到：{hyp_confidence}。", error=True)
        return write_hypothesis(record_id, parts[0], parts[1], hyp_confidence, {"supports": [s for s in source_refs], "source_refs": source_refs})
    if kind not in VALID_KINDS or confidence not in VALID_CONFIDENCE or sensitivity not in VALID_SENSITIVITY: return text_result("拒绝写入：kind / confidence / sensitivity 不合法。", error=True)
    if tier not in {"full", "light"}: return text_result("拒绝写入：tier 只能是 full 或 light。", error=True)
    if not summary: return text_result("拒绝写入：summary 不能为空。", error=True)
    # 2.7.0: salience is range-checked at write time for BOTH tiers — the old code
    # only guarded tier=light, so salience: 99 sailed into full records while
    # downstream clamped/ignored it silently; int() garbage became a raw -32603.
    raw_salience = data.get("salience")
    salience: int | None = None
    if raw_salience not in (None, ""):
        try:
            salience = int(raw_salience)
        except (TypeError, ValueError):
            return text_result(f"拒绝写入：salience 必须是 0-{3} 的整数，收到：{raw_salience}。", error=True)
        if not 0 <= salience <= 3: return text_result(f"拒绝写入：salience 超出 0-3，收到：{salience}。", error=True)
    if tier == "light" and (salience if salience is not None else 1) > 1: return text_result("拒绝写入：活动足迹微型记录（tier=light）的 salience 不得超过 1。", error=True)
    if kind in {"state", "decision", "model", "value", "heuristic", "rule", "preference"} and not domain: return text_result(f"拒绝写入：{kind} 类型必须提供 domain。", error=True)
    # 2.7.0: write-path validation now mirrors validate_memory exactly (schema.py).
    # "learning" used to be accepted here and rejected by the auditor — a record
    # born already invalid ("写入即废"); the legal branch ids are listed on refusal.
    legal_domains = branch_ids(ROOT)
    if domain and domain not in legal_domains:
        return text_result(f"拒绝写入：未知 domain：{domain}。合法值是 memory/branches 的 branch id：{'、'.join(sorted(legal_domains))}。", error=True)
    for date_field in ("valid_from", "last_confirmed", "date_end"):
        date_value = data.get(date_field)
        if date_value not in (None, "") and not valid_date_string(date_value):
            return text_result(f"拒绝写入：{date_field} 必须是 {DATE_FORMAT_HINT} 的合法日历日期，收到：{date_value}。", error=True)
    captures_index = discover_captures(ROOT)
    if capture_id:
        capture_meta = captures_index.get(capture_id)
        if not capture_meta: return text_result("拒绝写入：capture_id 不存在；先保存原话或附件。", error=True)
        source_path = str(capture_meta.get("source_path") or "").strip()
        if source_path: source_refs.append(source_path)
        verbatim_refs.append(f"fragment.capture.{capture_id}")
    if "current-conversation" in source_refs and not verbatim_refs: return text_result("拒绝写入：current-conversation 不能代替原话；必须提供 capture_id 或 verbatim_refs。", error=True)
    linked_capture_ids = set()
    if capture_id: linked_capture_ids.add(capture_id)
    for ref in verbatim_refs:
        if ref.startswith("fragment.capture."): linked_capture_ids.add(ref.removeprefix("fragment.capture."))
    # 2.7.0 atomicity: every capture reference is verified BEFORE anything is
    # written. The old order wrote the record file first and dereferenced
    # verbatim_refs during link_record — a bogus ref left an orphan record on
    # disk while the caller saw an RPC error, and the id was then stuck
    # ("拒绝覆盖已有记录") on retry.
    unknown_captures = sorted(cid for cid in linked_capture_ids if cid not in captures_index)
    if unknown_captures:
        return text_result(f"拒绝写入：verbatim_refs 指向不存在的 capture：{', '.join(unknown_captures)}；先保存原话或修正引用。", error=True)
    path = RECORDS / f"{record_id}.md"
    today = dt.date.today().isoformat(); valid_from = data.get("valid_from"); last_confirmed = data.get("last_confirmed") or today
    created = False
    try:
        with mutation_lock(ROOT):
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists(): return text_result(f"拒绝覆盖已有记录：{path.name}。", error=True)
            payload = "\n".join(["---", f"id: {record_id}", f"kind: {kind}", "status: current", f"confidence: {confidence}", f"sensitivity: {sensitivity}", f"tier: {tier}"])
            if valid_from not in (None, ""): payload += f"\nvalid_from: {valid_from}"
            if last_confirmed not in (None, ""): payload += f"\nlast_confirmed: {last_confirmed}"
            if domain: payload += f"\ndomain: {domain}\nparent_ids: {domain}"
            for key in ("salience", "phase", "date_end", "date_precision", "date_basis", "entity_refs", "record_role"):
                value = join_list_value(data.get(key))
                if value not in (None, ""):
                    payload += f"\n{key}: {value}"
            for key in ("related_ids", "aliases"):
                value = join_list_value(data.get(key))
                if value: payload += f"\n{key}: {value}"
            if source_refs: payload += "\nsource_refs: " + "; ".join(dict.fromkeys(source_refs))
            if verbatim_refs: payload += "\nverbatim_refs: " + "; ".join(dict.fromkeys(verbatim_refs))
            payload += "\nschema_version: 2.0.0\n---\n\n" + summary + "\n"
            atomic_write_text(path, payload); created = True
            if path.read_text(encoding="utf-8") != payload: raise RuntimeError("记录回读校验失败")
            for linked_capture_id in sorted(linked_capture_ids):
                link_record(linked_capture_id, record_id, root=ROOT)
    except Exception as exc:
        if created:
            path.unlink(missing_ok=True)
            try: repair_ledger(ROOT)
            except Exception: pass
        return text_result(f"拒绝写入：记录已回滚（{exc}）。", error=True)
    ledger = load_ledger(ROOT)
    unlinked = [cid for cid in sorted(linked_capture_ids) if record_id not in (ledger.get(cid, {}).get("record_ids") or [])]
    if unlinked:
        return text_result(f"记录已写入但台账链接缺失：{', '.join(unlinked)}；请运行 personal_derivation_status 检查后再补链。", error=True)
    return text_result(f"已创建：{path.name}；关联 capture：{', '.join(sorted(linked_capture_ids)) or '无'}。capture 仍为 pending，完成本轮全部拆分后必须 finalize。视图将在下次读取时自动重建（2.7.0）。")



def finalize_capture_tool(data: dict[str, Any]) -> dict[str, Any]:
    capture_id = str(data.get("capture_id", "")).strip(); disposition = str(data.get("disposition", "")).strip(); reason = str(data.get("reason", "")).strip()
    try:
        entry = finalize_capture(capture_id, disposition, reason, root=ROOT)
    except ValueError as exc:
        return text_result(f"拒绝关闭 capture：{exc}", error=True)
    # 2.7.0: pending captures are read straight from the ledger audit — the old
    # code ran validate_memory without --json and called .get() on its *string*
    # output, so pending_captures was always [] and the mid-turn reminder never
    # fired. Finalize only mutates the ledger; sibling captures still open is a
    # normal mid-turn state (the whole-turn gate is session_check), so the audit
    # result rides along as information, never as this tool's error flag.
    audit = audit_ledger(ROOT)
    payload: dict[str, Any] = {"status": "finalized", "capture": entry, "ledger": {"status": audit["status"], "errors": audit["errors"], "warnings": audit["warnings"]}, "pending_captures": audit["pending_capture_ids"]}
    if audit["pending_capture_ids"]:
        payload["note"] = "本轮还有未闭环 capture（多 capture 轮属正常中态）；全部关闭后先跑 personal_session_check 再回答"
    if entry.get("already_closed"):
        payload["note"] = "该 capture 已按相同 disposition 关闭过，本次为幂等重入，台账未变更"
    return text_result(json.dumps(payload, ensure_ascii=False, indent=2))

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
    # 2.7.0: "下个月吧" used to be stored verbatim as due_at, parse_day silently
    # bucketed the row as undated, and the followup never fired — a reminder
    # black hole. Either a real calendar date, or an explicit due_rule with no
    # date at all; anything in between is refused at the door.
    due_at = data.get("due_at")
    if due_at not in (None, "") and not valid_date_string(due_at):
        return text_result(f"拒绝写入：due_at 必须是 {DATE_FORMAT_HINT} 的合法日期，收到：{due_at}。相对说法请换算成具体日期；不想定死日期就只写 due_rule（如 next-relevant-activation），不要传 due_at。", error=True)
    path = V2 / "followups.jsonl"
    with mutation_lock(ROOT):
        rows = read_jsonl(path)
        if any(row.get("id") == ident for row in rows): return text_result("拒绝覆盖已有 followup。", error=True)
        rows.append({"id": ident, "prompt": prompt, "context": context, "status": "pending", "due_at": due_at if due_at not in (None, "") else None, "due_rule": data.get("due_rule") or "next-relevant-activation", "source_refs": data.get("source_refs") or [], "created_at": dt.date.today().isoformat(), "last_checked_at": None, "snooze_until": None, "priority": data.get("priority") or "normal"})
        payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in sorted(rows, key=lambda row: row["id"]))
        write_text_atomic(path, payload)
    # Policy wants every followup to carry source refs and an expiry rule; remind on
    # the way out instead of refusing the write (audit-only stance, hard constraint #1).
    missing_fields = loose_followup_fields(data)
    reminder = f"\n\n提醒：本条缺 {'、'.join(missing_fields)}；回访政策要求每条必带来源与到期规则，下次登记请补全。" if missing_fields else ""
    return text_result(f"已登记待回访：{ident}{reminder}")


def resolve_followup_tool(data: dict[str, Any]) -> dict[str, Any]:
    ident = str(data.get("id", "")).strip()
    try:
        closed = resolve_followup(ident, resolution=str(data.get("resolution", "")).strip(), note=str(data.get("note", "")).strip(), capture_id=str(data.get("capture_id", "")).strip())
    except ValueError as exc:
        return text_result(f"拒绝关闭回访：{exc}", error=True)
    bound = f"\n已绑定用户回答原话 capture：{closed['answer_capture_id']}" if closed.get("answer_capture_id") else ""
    return text_result(f"已关闭回访：{ident}（{closed['status']}）{bound}")


def add_hypothesis(data: dict[str, Any]) -> dict[str, Any]:
    ident = str(data.get("id", "")).strip(); claim = str(data.get("claim", "")).strip(); mechanism = str(data.get("mechanism", "")).strip()
    if not ID_RE.fullmatch(ident) or not claim or not mechanism: return text_result("拒绝写入：hypothesis id、claim、mechanism 必填且合法。", error=True)
    hypothesis_confidence = str(data.get("confidence") or "low").strip()
    if hypothesis_confidence not in VALID_CONFIDENCE:
        return text_result(f"拒绝写入：confidence 必须是 {'/'.join(sorted(VALID_CONFIDENCE))}，收到：{hypothesis_confidence}。", error=True)
    return write_hypothesis(ident, claim, mechanism, hypothesis_confidence, data)


def write_hypothesis(ident: str, claim: str, mechanism: str, confidence: str, data: dict[str, Any]) -> dict[str, Any]:
    path = V2 / "hypotheses.jsonl"
    with mutation_lock(ROOT):
        rows = read_jsonl(path)
        if any(row.get("id") == ident for row in rows): return text_result("拒绝覆盖已有 hypothesis。", error=True)
        row = {"id": ident, "kind": "causal_hypothesis", "status": "candidate", "claim": claim, "mechanism": mechanism, "supports": data.get("supports") or [], "contradicts": data.get("contradicts") or [], "alternatives": data.get("alternatives") or [], "scope": data.get("scope") or "", "confidence": confidence, "source_refs": data.get("source_refs") or [], "created_at": dt.date.today().isoformat(), "last_reviewed_at": None}
        rows.append(row)
        payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in sorted(rows, key=lambda item: item["id"]))
        write_text_atomic(path, payload)
    return text_result(f"已登记候选因果假设：{ident}")


UNKNOWN_METHOD = object()


def handle(method: str, params: dict[str, Any]) -> Any:
    if method == "initialize": return {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}, "resources": {}}, "serverInfo": {"name": "personal-understanding", "version": skill_version()}, "instructions": "这是本地个人理解 v2 MCP。个人补充必须先保存原话，再生成派生档案。"}
    if method == "tools/list": return {"tools": tool_definitions()}
    if method == "resources/list": return {"resources": [{"uri": "personal://catalog/survey", "name": "个人理解 v2 全局勘察", "mimeType": "application/json", "description": "时间主干、实体、情境、当前状态和待回访。"}, {"uri": "personal://skill/info", "name": "个人理解 Skill 信息", "mimeType": "text/markdown", "description": "v2 规则和入口。"}]}
    if method == "resources/read":
        uri = str(params.get("uri", ""))
        if uri == "personal://catalog/survey":
            failed = fresh_views_or_refuse()
            if failed: raise RuntimeError(failed)
            code, output = run_script("catalog_context.py", ["--view", "survey", "--maintenance"]); return {"contents": [{"uri": uri, "mimeType": "application/json", "text": output}]} if not code else (_ for _ in ()).throw(RuntimeError(output))
        if uri == "personal://skill/info": return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": (ROOT / "SKILL.md").read_text(encoding="utf-8")}]} 
        raise ValueError(f"未知资源：{uri}")
    if method == "tools/call":
        name = str(params.get("name", "")); args = params.get("arguments", {})
        if not isinstance(args, dict): return text_result("arguments 必须是对象。", error=True)
        if name == "personal_preflight_turn":
            text = args.get("text")
            if not isinstance(text, str): return text_result("text 必须是字符串。", error=True)
            tier = str(args.get("tier") or "auto")
            try:
                receipt = create_receipt(text, turn_id=str(args.get("turn_id", "") or "") or None, conversation_id=str(args.get("conversation_id", "") or "") or None, tier=tier, root=ROOT)
            except ValueError as exc: return text_result(f"preflight 失败：{exc}", error=True)
            # §8: the low-signal fast path promises "pick an entry from the due
            # follow-ups + current-state snapshot in the preflight output" — make
            # that literally true on the MCP path too, matching preflight_context.py.
            # Personal-required turns get the bundle; others stay lean (just the
            # receipt) so skip-tier turns pay no extra tokens.
            payload: dict[str, Any] = {"turn_receipt": receipt}
            if receipt.get("requires_personal_understanding"):
                from preflight_context import maintenance_reminders, state_snapshot
                checks = check_followups()
                payload["followups"] = {"due": checks["due"], "undated_pending": checks["undated_pending"]}
                payload["current_state_snapshot"] = state_snapshot()
                payload["maintenance_reminders"] = maintenance_reminders()
            return text_result(json.dumps(payload, ensure_ascii=False, indent=2))
        if name == "personal_catalog":
            ok, message, maintenance = read_gate(args)
            if not ok: return text_result(message, error=True)
            failed = fresh_views_or_refuse()
            if failed: return text_result(failed, error=True)
            view = str(args.get("view", "survey"));
            if view not in {"survey", "routing", "full"}: return text_result("view 不合法。", error=True)
            cmd = ["--view", view, "--capture-id", str(args.get("capture_id", "")).strip()];
            if maintenance: cmd += ["--maintenance"]
            if args.get("query"): cmd += ["--query", str(args["query"])]
            if args.get("domain"): cmd += ["--domain", str(args["domain"])]
            if args.get("max_chars"): cmd += ["--max-chars", str(args["max_chars"])]
            code, output = run_script("catalog_context.py", cmd); return text_result(output, error=bool(code))
        if name == "personal_retrieve":
            ok, message, maintenance = read_gate(args)
            if not ok: return text_result(message, error=True)
            failed = fresh_views_or_refuse()
            if failed: return text_result(failed, error=True)
            ids = args.get("ids") or []; query = str(args.get("query", "")); level = str(args.get("level", "probe")); cmd = ["--level", level, "--capture-id", str(args.get("capture_id", "")).strip()]
            if maintenance: cmd += ["--maintenance"]
            if ids: cmd += ["--event-ids", ",".join(str(item) for item in ids), "--entity-ids", ",".join(str(item) for item in ids)]
            if query: cmd += ["--query", query]
            if args.get("max_chars"): cmd += ["--max-chars", str(args["max_chars"])]
            code, output = run_script("retrieve_v2.py", cmd); return text_result(output, error=bool(code))
        if name == "personal_capture_user_turn": return capture(args)
        if name == "personal_add_record": return add_record(args)
        if name == "personal_finalize_capture": return finalize_capture_tool(args)
        # 2.8.0 瘦身：personal_derivation_status 已并入 personal_validate；此处拦截
        # 仅作迁移期指针（直接 302 语义而非静默吞掉），一个发布周期后删除本分支。
        if name == "personal_derivation_status":
            return text_result("personal_derivation_status 已于 2.8.0 并入 personal_validate：闭环状态（pending/孤立捕获/链接漂移）即其 derivation 段。", error=True)
        if name == "personal_add_followup": return add_followup(args)
        if name == "personal_resolve_followup": return resolve_followup_tool(args)
        # 2.8.0 瘦身：personal_add_hypothesis 已并入 personal_add_record（kind=causal_hypothesis）。迁移期指针，一个发布周期后删除。
        if name == "personal_add_hypothesis":
            return text_result("personal_add_hypothesis 已于 2.8.0 并入 personal_add_record：用 kind=causal_hypothesis，summary 写 'claim || mechanism'（以 ' || ' 分隔），confidence 取 low/medium/high；supports/contradicts/alternatives/scope 走 source_refs/related_ids 标注。", error=True)
        if name == "personal_add_feedback":
            cmd = ["--feedback-id", str(args.get("feedback_id", "")), "--outcome", str(args.get("outcome", ""))]
            if args.get("capture_id"): cmd += ["--capture-id", str(args["capture_id"])]
            if args.get("memory_ids"): cmd += ["--memory-ids", str(args["memory_ids"])]
            if args.get("note"): cmd += ["--note", str(args["note"])]
            code, output = run_script("record_feedback.py", cmd); return text_result(output, error=bool(code))
        if name == "personal_session_check":
            # 2.7.0: exit 2 (warnings-only) no longer maps to isError — warnings are
            # "usable but must be reported", and the output text carries them; only a
            # hard fail (exit 1) is an error result. session_check.py itself now
            # audits the LATEST receipt when turn_id is omitted, so the turn gate can
            # no longer be bypassed by forgetting the argument.
            # 2.8.0: default light mode — turn gate + pending + followups, skipping
            # the full-library validate subprocess (seconds -> ms). Pass light=false
            # for the old full gate (maintenance rounds / migration acceptance).
            cmd = ["session_check.py"] + (["--turn-id", str(args["turn_id"])] if args.get("turn_id") else []) + (["--allow-warnings"] if args.get("allow_warnings") else [])
            # 2.7.0: `if args.get(...)` would swallow stale_days=0 — a legitimate
            # value ("everything pending counts as stale"). Only an ABSENT key
            # falls back to the script default.
            if args.get("stale_days") is not None: cmd += ["--stale-days", str(args["stale_days"])]
            if args.get("light", True): cmd += ["--light"]
            code, output = run_script(cmd[0], cmd[1:]); return text_result(output, error=(code == 1))
        if name == "personal_validate":
            # 2.8.0: absorbs derivation_status — derivation=embed appends the
            # capture→records ledger audit (pending / orphan / link drift) to the
            # structural validation payload.
            failed = fresh_views_or_refuse()
            if failed: return text_result(failed, error=True)
            cmd = ["--json", "--require-closed-captures"] + (["--strict"] if args.get("strict") else []); code, output = run_script("validate_memory.py", cmd)
            if args.get("derivation", True):
                try:
                    payload = json.loads(output) if isinstance(output, str) else output
                    if isinstance(payload, dict):
                        payload["derivation_ledger_audit"] = audit_ledger(ROOT)
                        output = json.dumps(payload, ensure_ascii=False, indent=2)
                except (json.JSONDecodeError, TypeError):
                    output = f"{output}\n\n[derivation_ledger_audit]\n" + json.dumps(audit_ledger(ROOT), ensure_ascii=False, indent=2)
            return text_result(output, error=bool(code))
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
        except TimeoutError as exc:
            # Lock starvation is a clean, retryable refusal — not a protocol error.
            # As -32603 it looked like a server crash and invited blind retries.
            if isinstance(msg, dict) and "id" in msg:
                print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": f"写锁等待超时，档案正被其他进程占用：{exc}。请稍后重试。"}], "isError": True}}, ensure_ascii=False), flush=True)
        except Exception as exc:
            if isinstance(msg, dict) and "id" in msg: print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(exc)}}, ensure_ascii=False), flush=True)


if __name__ == "__main__": main()
