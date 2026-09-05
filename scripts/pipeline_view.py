#!/usr/bin/env python3
"""Pipeline timeline view (2.6.0, SKILL §可视化审计契约 第一步).

把"一轮对话的一生"拼成一张只读图：turn receipt（判了什么档、为什么）→ capture
（原话存哪、哈希）→ 派生台账（闭环到哪、挂了哪些记录）→ 检索 trace（走了哪条
查询、选了什么、联想带了什么）。原料全部来自既有事实源，本工具只读拼装，
不生成新的档案内容。它同时是验收工具：足迹纪律、闭环完整性、检索捞偏都能
在这里一眼回放。

用法：
  python scripts/pipeline_view.py --turn-id turn.abc123            # 单轮 HTML+摘要
  python scripts/pipeline_view.py --latest 5                       # 最近 5 轮索引
  python scripts/pipeline_view.py --turn-id X --format text        # 纯文本到 stdout
"""
from __future__ import annotations

from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()
import argparse
import html
import json
from pathlib import Path

from catalog_utils import ROOT
from derivation_ledger import discover_captures, load_ledger
from turn_receipts import read_receipt, receipt_dir
from v2_archive import V2_ROOT

TRACES = V2_ROOT / "traces"


def receipt_for_capture(capture_id: str) -> dict | None:
    """Find the turn receipt that owns this capture: same-name first, then scan
    receipts whose capture_ids list contains it (capture_id and turn_id often
    differ, e.g. capture.20260905-eval-ideas vs turn.4d81af60…)."""
    direct = read_receipt(capture_id, ROOT)
    if direct and (capture_id in ([direct.get("turn_id")] + list(direct.get("capture_ids") or []))):
        return direct
    rdir = receipt_dir(ROOT)
    if rdir.exists():
        for path in sorted(rdir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if capture_id in list(row.get("capture_ids") or []) or row.get("capture_id") == capture_id:
                return row
    return direct


def load_traces_for(capture_id: str) -> list[dict]:
    rows: list[dict] = []
    if not TRACES.exists():
        return rows
    for path in sorted(TRACES.glob("trace-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or capture_id not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("capture_id") == capture_id:
                rows.append(row)
    rows.sort(key=lambda row: row.get("at") or "")
    return rows


def latest_capture_ids(limit: int) -> list[str]:
    entries = load_ledger(ROOT)
    ranked = sorted(entries.values(), key=lambda e: e.get("captured_at") or "", reverse=True)
    return [str(e.get("capture_id")) for e in ranked[:limit] if e.get("capture_id")]


def assemble(capture_id: str) -> dict:
    ledger_entry = load_ledger(ROOT).get(capture_id, {})
    captures = discover_captures(ROOT)
    meta = captures.get(capture_id, {})
    turn_id = capture_id if str(capture_id).startswith("turn.") else ""
    receipt = receipt_for_capture(capture_id)
    traces = load_traces_for(capture_id)
    source_path = str(ledger_entry.get("source_path") or meta.get("source_path") or "")
    verbatim = ""
    if source_path and (ROOT / source_path).exists():
        verbatim = (ROOT / source_path).read_text(encoding="utf-8", errors="replace")[:2000]
    return {"capture_id": capture_id, "receipt": receipt, "ledger": ledger_entry,
            "trace_count": len(traces), "traces": traces, "verbatim_head": verbatim,
            "source_path": source_path}


def text_view(data: dict) -> str:
    lines: list[str] = []
    receipt = data.get("receipt") or {}
    ledger = data.get("ledger") or {}
    lines.append(f"== 管线时间线：{data['capture_id']} ==")
    lines.append(f"receipt: signal={receipt.get('signal')} tier={receipt.get('tier')} reasons={receipt.get('reasons')} suppressed={receipt.get('reasons_suppressed')}")
    lines.append(f"capture: {data.get('source_path') or '（无 capture——维护读取或尚未捕获）'}")
    lines.append(f"ledger: status={ledger.get('status')} records={ledger.get('record_ids')} closed_at={ledger.get('finalized_at')}")
    if ledger.get("finalization_reason"):
        lines.append(f"  reason: {ledger['finalization_reason']}")
    lines.append(f"retrieval traces: {data.get('trace_count')} 次")
    for trace in data.get("traces", []):
        sel = trace.get("selected") or {}
        assoc = trace.get("associations") or {}
        lines.append(f"  - {trace.get('at')} [{trace.get('level')}] q={str(trace.get('query'))[:38]} scoring={trace.get('scoring')} events={len(sel.get('event_ids') or [])} entities={len(sel.get('entity_ids') or [])} assoc={assoc.get('returned')} seeds={len(assoc.get('seeds') or [])}")
    if data.get("verbatim_head"):
        lines.append("verbatim head:")
        lines.append("  " + data["verbatim_head"][:400].replace("\n", "\n  "))
    return "\n".join(lines)


def html_view(data: dict) -> str:
    esc = html.escape
    receipt = data.get("receipt") or {}
    ledger = data.get("ledger") or {}
    rows: list[str] = []
    rows.append(f"<h1>一轮对话的一生 · {esc(data['capture_id'])}</h1>")

    def kv(items: list[tuple[str, object]]) -> str:
        return "".join(f"<tr><th>{esc(str(k))}</th><td>{esc(str(v))}</td></tr>" for k, v in items)

    rows.append("<h2>1 · 内容判定（turn receipt）</h2><table>" + kv([
        ("signal", receipt.get("signal")), ("tier", receipt.get("tier")),
        ("reasons", ", ".join(receipt.get("reasons") or []) or "—"),
        ("reasons_suppressed", ", ".join(receipt.get("reasons_suppressed") or []) or "—"),
        ("capture 状态", receipt.get("capture_status")), ("闭环状态", receipt.get("closure_status")),
    ]) + "</table>")

    rows.append("<h2>2 · 原话捕获（immutable capture）</h2><table>" + kv([
        ("来源", data.get("source_path") or "—"),
        ("message_kind", ledger.get("message_kind")),
        ("captured_at", ledger.get("captured_at")),
        ("sha256", (ledger.get("content_sha256") or "")[:16] + "…"),
    ]) + "</table>")
    if data.get("verbatim_head"):
        rows.append(f"<pre class='verbatim'>{esc(data['verbatim_head'][:800])}</pre>")

    rows.append("<h2>3 · 派生闭环（capture → records）</h2><table>" + kv([
        ("status", ledger.get("status")),
        ("挂靠记录", ", ".join(ledger.get("record_ids") or []) or "—"),
        ("closed_at", ledger.get("finalized_at")),
        ("关闭理由", ledger.get("finalization_reason") or "—"),
    ]) + "</table>")

    traces = data.get("traces") or []
    rows.append(f"<h2>4 · 检索轨迹（{len(traces)} 次）</h2>")
    for trace in traces:
        sel = trace.get("selected") or {}
        assoc = trace.get("associations") or {}
        stopped = trace.get("stopped") or {}
        rows.append("<div class='trace'><table>" + kv([
            ("时间", trace.get("at")), ("query", str(trace.get("query"))[:120]),
            ("scoring", trace.get("scoring")), ("level", trace.get("level")),
            ("选中", f"events {len(sel.get('event_ids') or [])} / entities {len(sel.get('entity_ids') or [])} / knowledge {len(sel.get('knowledge_ids') or [])}"),
            ("联想", f"seeds {len(assoc.get('seeds') or [])} → {assoc.get('returned')} 条 via {', '.join(str(v).replace('entity.concept.', 'concept.') for v in (assoc.get('via') or [])[:4])}"),
            ("停用", f"events {stopped.get('event_count')} / entities {stopped.get('entity_count')} — {stopped.get('reason')}"),
            ("因果假设", f"carried {trace.get('hypotheses', {}).get('carried')} / omitted {trace.get('hypotheses', {}).get('omitted')}"),
        ]) + "</table></div>")

    style = "<style>body{font-family:'Segoe UI',system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1c2430}h1{font-size:20px}h2{font-size:15px;margin:22px 0 8px;border-bottom:1px solid #d7dde5;padding-bottom:4px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #d7dde5;padding:5px 8px;text-align:left;vertical-align:top}th{background:#f2f5f8;width:130px;font-weight:600}pre.verbatim{background:#f7f8fa;border:1px solid #d7dde5;padding:10px;white-space:pre-wrap;font-size:12px}.trace{margin:10px 0}</style>"
    return "<!doctype html><meta charset='utf-8'><title>管线时间线</title>" + style + "".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--turn-id", default="", help="turn/capture id to render")
    ap.add_argument("--latest", type=int, default=0, help="index the N most recent captures")
    ap.add_argument("--format", choices=("html", "text"), default="html")
    ap.add_argument("--out", default="", help="write HTML here (default: dashboard/pipeline-<id>.html)")
    args = ap.parse_args()
    if args.latest:
        for capture_id in latest_capture_ids(args.latest):
            print(text_view(assemble(capture_id)))
            print()
        return 0
    if not args.turn_id:
        ap.error("需要 --turn-id 或 --latest N")
    data = assemble(args.turn_id.strip())
    if args.format == "text":
        print(text_view(data))
        return 0
    out = Path(args.out) if args.out else ROOT / "dashboard" / f"pipeline-{args.turn_id.strip()}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_view(data), encoding="utf-8")
    print(text_view(data))
    print(f"\nHTML -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
