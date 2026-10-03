#!/usr/bin/env python3
"""Pipeline timeline view (2.6.0, SKILL §可视化审计契约 第一步).

把"一轮对话的一生"拼成一张只读图：turn receipt（判了什么档、为什么）→ capture
（原话存哪、哈希）→ 派生台账（闭环到哪、挂了哪些记录）→ 检索 trace（走了哪条
查询、选了什么、联想带了什么）。原料全部来自既有事实源，本工具只读拼装，
不生成新的档案内容。它同时是验收工具：足迹纪律、闭环完整性、检索捞偏都能
在这里一眼回放。

用法：
  python scripts/pipeline_view.py --turn-id turn.abc123            # 单轮 HTML+摘要
  python scripts/pipeline_view.py --turn-id capture.20260905-x     # 同上：capture id 也会解析到所属回合的全部 capture
  python scripts/pipeline_view.py --latest 5                       # 最近 5 轮索引（stdout 摘要 + dashboard/pipeline-latest.html）
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


def assemble(identifier: str) -> dict:
    """Assemble the WHOLE turn pipeline (2.7.0).

    ``identifier`` may be a turn id or a capture id — both resolve to the owning
    turn and every capture it produced. The old code rendered only the one
    capture passed in, hiding sibling captures of multi-capture turns (the
    normal shape: one preflight → N captures → N finalizations), so a turn
    reviewed through its second capture looked like it never derived anything."""
    identifier = identifier.strip()
    ledger = load_ledger(ROOT)
    captures = discover_captures(ROOT)
    receipt = read_receipt(identifier, ROOT) if identifier.startswith("turn.") else receipt_for_capture(identifier)
    turn_id = str((receipt or {}).get("turn_id") or (identifier if identifier.startswith("turn.") else ""))
    capture_ids: list[str] = []
    if not identifier.startswith("turn.") and (identifier in captures or identifier in ledger):
        capture_ids.append(identifier)
    for cid in (receipt or {}).get("capture_ids") or []:
        if cid not in capture_ids:
            capture_ids.append(cid)
    entries: list[dict] = []
    traces: list[dict] = []
    for cid in capture_ids:
        entry = ledger.get(cid, {})
        meta = captures.get(cid, {})
        source_path = str(entry.get("source_path") or meta.get("source_path") or "")
        verbatim = ""
        if source_path and (ROOT / source_path).exists():
            verbatim = (ROOT / source_path).read_text(encoding="utf-8", errors="replace")[:2000]
        traces.extend(load_traces_for(cid))
        entries.append({"capture_id": cid, "ledger": entry, "source_path": source_path, "verbatim_head": verbatim})
    traces.sort(key=lambda row: row.get("at") or "")
    return {"title": turn_id or (capture_ids[0] if capture_ids else identifier), "turn_id": turn_id,
            "receipt": receipt, "captures": entries, "traces": traces, "trace_count": len(traces)}


def text_view(data: dict) -> str:
    lines: list[str] = []
    receipt = data.get("receipt") or {}
    lines.append(f"== 管线时间线：{data['title']} ==")
    lines.append(f"turn: {data.get('turn_id') or '—'}")
    lines.append(f"receipt: signal={receipt.get('signal')} tier={receipt.get('tier')} reasons={receipt.get('reasons')} suppressed={receipt.get('reasons_suppressed')}")
    for entry in data.get("captures") or []:
        ledger = entry.get("ledger") or {}
        lines.append(f"capture: {entry['capture_id']} -> {entry.get('source_path') or '（无 capture 文件——维护读取或尚未捕获）'}")
        lines.append(f"ledger: status={ledger.get('status')} records={ledger.get('record_ids')} closed_at={ledger.get('finalized_at')}")
        if ledger.get("finalization_reason"):
            lines.append(f"  reason: {ledger['finalization_reason']}")
        if entry.get("verbatim_head"):
            lines.append("verbatim head:")
            lines.append("  " + entry["verbatim_head"][:400].replace("\n", "\n  "))
    lines.append(f"retrieval traces: {data.get('trace_count')} 次")
    for trace in data.get("traces", []):
        sel = trace.get("selected") or {}
        assoc = trace.get("associations") or {}
        lines.append(f"  - {trace.get('at')} [{trace.get('level')}] q={str(trace.get('query'))[:38]} scoring={trace.get('scoring')} events={len(sel.get('event_ids') or [])} entities={len(sel.get('entity_ids') or [])} assoc={assoc.get('returned')} seeds={len(assoc.get('seeds') or [])}")
    return "\n".join(lines)


STYLE = "<style>body{font-family:'Segoe UI',system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1c2430}h1{font-size:20px}h2{font-size:15px;margin:22px 0 8px;border-bottom:1px solid #d7dde5;padding-bottom:4px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #d7dde5;padding:5px 8px;text-align:left;vertical-align:top}th{background:#f2f5f8;width:130px;font-weight:600}pre.verbatim{background:#f7f8fa;border:1px solid #d7dde5;padding:10px;white-space:pre-wrap;font-size:12px}.trace{margin:10px 0}</style>"


def html_view(data: dict) -> str:
    esc = html.escape
    receipt = data.get("receipt") or {}
    rows: list[str] = []
    rows.append(f"<h1>一轮对话的一生 · {esc(str(data['title']))}</h1>")

    def kv(items: list[tuple[str, object]]) -> str:
        return "".join(f"<tr><th>{esc(str(k))}</th><td>{esc(str(v))}</td></tr>" for k, v in items)

    rows.append("<h2>1 · 内容判定（turn receipt）</h2><table>" + kv([
        ("turn_id", data.get("turn_id") or "—"),
        ("signal", receipt.get("signal")), ("tier", receipt.get("tier")),
        ("reasons", ", ".join(receipt.get("reasons") or []) or "—"),
        ("reasons_suppressed", ", ".join(receipt.get("reasons_suppressed") or []) or "—"),
        ("capture 状态", receipt.get("capture_status")), ("闭环状态", receipt.get("closure_status")),
    ]) + "</table>")

    for index, entry in enumerate(data.get("captures") or [], start=1):
        ledger = entry.get("ledger") or {}
        label = f"2.{index}" if len(data.get("captures") or []) > 1 else "2"
        rows.append(f"<h2>{label} · 原话捕获 + 派生闭环 · {esc(str(entry['capture_id']))}</h2><table>" + kv([
            ("来源", entry.get("source_path") or "—"),
            ("message_kind", ledger.get("message_kind")),
            ("captured_at", ledger.get("captured_at")),
            ("sha256", (ledger.get("content_sha256") or "")[:16] + "…"),
            ("闭环 status", ledger.get("status")),
            ("挂靠记录", ", ".join(ledger.get("record_ids") or []) or "—"),
            ("closed_at", ledger.get("finalized_at")),
            ("关闭理由", ledger.get("finalization_reason") or "—"),
        ]) + "</table>")
        if entry.get("verbatim_head"):
            rows.append(f"<pre class='verbatim'>{esc(entry['verbatim_head'][:800])}</pre>")

    traces = data.get("traces") or []
    rows.append(f"<h2>3 · 检索轨迹（{len(traces)} 次）</h2>")
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

    return "<!doctype html><meta charset='utf-8'><title>管线时间线</title>" + STYLE + "".join(rows)


def latest_html(entries: list[dict]) -> str:
    esc = html.escape
    cards = "".join(f"<div class='card'><pre>{esc(text_view(data))}</pre></div>" for data in entries)
    cards_style = "<style>.card{border:1px solid #d7dde5;border-radius:6px;margin:14px 0;padding:4px 14px;background:#fbfcfd}pre{white-space:pre-wrap;font-size:12px;line-height:1.5}</style>"
    return ("<!doctype html><meta charset='utf-8'><title>最近管线</title>" + STYLE + cards_style
            + f"<h1>最近 {len(entries)} 轮管线索引</h1>" + cards)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--turn-id", default="", help="turn/capture id to render (either form renders the whole turn)")
    ap.add_argument("--latest", type=int, default=0, help="index the N most recent captures")
    ap.add_argument("--format", choices=("html", "text"), default="html")
    ap.add_argument("--out", default="", help="write HTML here (default: dashboard/pipeline-<turn_id>.html)")
    args = ap.parse_args()
    if args.latest:
        entries = [assemble(capture_id) for capture_id in latest_capture_ids(args.latest)]
        for data in entries:
            print(text_view(data))
            print()
        # 2.7.0: --latest used to print text only — the dashboard/ contract
        # (SKILL 可视化审计契约) promises an HTML artifact, so the index page is
        # always written, whichever --format the stdout summary uses.
        out = Path(args.out) if args.out else ROOT / "dashboard" / "pipeline-latest.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(latest_html(entries), encoding="utf-8")
        print(f"HTML -> {out.relative_to(ROOT)}")
        return 0
    if not args.turn_id:
        ap.error("需要 --turn-id 或 --latest N")
    data = assemble(args.turn_id.strip())
    if args.format == "text":
        print(text_view(data))
        return 0
    page_name = str(data.get("turn_id") or data["title"])
    out = Path(args.out) if args.out else ROOT / "dashboard" / f"pipeline-{page_name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_view(data), encoding="utf-8")
    print(text_view(data))
    print(f"\nHTML -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
