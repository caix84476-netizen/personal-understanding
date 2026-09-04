#!/usr/bin/env python3
"""Create the mandatory, durable routing receipt before a user-turn answer."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse, json, sys
from pathlib import Path
from followup_check import check_followups
from turn_receipts import classify_personal_turn, create_receipt
from v2_archive import load_v2

ROOT = Path(__file__).resolve().parents[1]


def state_snapshot() -> dict[str, object]:
    """Compact current-state snapshot for the low-signal fast path (2.5.0 §8).

    SKILL.md told the model to pick an entry point from "due follow-ups + the
    current-state snapshot in preflight output", but preflight never emitted any
    snapshot — the promised degraded read was half missing, so low-signal turns
    had to run a full survey or answer bare. Compact cards only (title + short
    summary); full detail stays behind catalog_context/retrieve_v2.
    """
    try:
        state = load_v2().get("current_state", {})
    except Exception:
        return {"available": False}
    def cards(items: list, limit: int) -> list[dict[str, str]]:
        out = []
        for item in (items or [])[:limit]:
            out.append({"id": item.get("id"), "title": item.get("title"), "summary": (str(item.get("summary") or ""))[:60]})
        return out
    return {
        "available": True,
        "as_of": state.get("as_of"),
        "core": cards(state.get("core"), 6),
        "tensions": cards(state.get("tensions"), 6),
        "conditions": cards(state.get("conditions"), 6),
    }


def classify_signal(text: str) -> dict[str, object]:
    decision = classify_personal_turn(text)
    return {"signal": decision["signal"], "note": "内容优先；润色、翻译、总结、看图等任务外形不能覆盖个人材料判定。", "requires_personal_understanding": decision["requires_personal_understanding"], "reasons": decision["reasons"]}

def _read(args: argparse.Namespace) -> str:
    if args.file: return Path(args.file).read_text(encoding="utf-8")
    if args.stdin: return sys.stdin.read()
    return args.text or ""

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("text", nargs="?", help="当前完整用户消息")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--file", help="UTF-8 完整用户消息文件")
    source.add_argument("--stdin", action="store_true", help="从 stdin 读取完整用户消息")
    ap.add_argument("--turn-id", default="", help="可复用的当前 turn 标识；同一 ID 不得对应不同消息")
    ap.add_argument("--tier", choices=["auto", "full", "light", "skip"], default="auto", help="两档调用的显式声明：full=完整档（含活动足迹轮次）；skip=明确跳过；auto=纯内容分类。light 已废弃（两档制改革），传入时按 full 处理")
    ap.add_argument("--conversation-id", default="")
    ap.add_argument("--budget", type=int, default=4000, help="兼容旧调用；不影响 receipt")
    ap.add_argument("--immediate-reason", choices=["correction", "attribution", "privacy", "structure", "compression", "decision"])
    ap.add_argument("--root", default="", help="归档根目录覆盖（测试/沙箱用；缺省为仓库根）")
    args = ap.parse_args()
    source_count = int(args.text is not None) + int(bool(args.file)) + int(bool(args.stdin))
    if source_count != 1:
        ap.error("必须且只能提供 text、--file 或 --stdin 之一")
    text = _read(args)
    root = Path(args.root) if args.root else ROOT
    receipt = create_receipt(text, turn_id=args.turn_id or None, conversation_id=args.conversation_id or None, tier=args.tier, root=root)
    required = bool(receipt["requires_personal_understanding"])
    low_information = len(text.strip()) <= 2
    review_alert = {"triggered": bool(args.immediate_reason), "reason": args.immediate_reason or "not-due"}
    auto_review = dict(review_alert)
    if args.immediate_reason:
        auto_review["alerts"] = [{"reason": args.immediate_reason, "action": "run semantic review before changing derived memory"}]
    result = {
        "activation": {
            "mode": "model-decision", "enforcement": "turn-receipt-required",
            "default": "capture-before-personal-analysis" if required else "skip-personal-archive",
            "mixed_query_rule": "先按消息内容判定；任务是润色、总结、翻译、看图或技术话题，都不能压过已出现的个人经历/状态/感受。",
            "next_step": "capture this exact turn" if required else "do not capture or derive personal memory for this turn",
        },
        "signal": classify_signal(text), "turn_receipt": receipt,
        # Keep the v2 scheduler shape for existing clients.  The receipt is
        # now the enforcement point; these fields remain routing context.
        "preflight": {"mode": "low-information" if low_information else "content-routed", "text_length": len(text)},
        "v2": {
            "followup_check": {"enabled": True, "version": "2.0.0"},
            "archive_audit": {"enabled": True, "version": "2.0.0"},
        },
        "followups": check_followups(),
        # The low-signal fast path reads "due follow-ups + current-state snapshot"
        # (SKILL.md 低信号降级读取); the snapshot was the missing half. Attached
        # only when the turn is personal-required, so skip-tier preflights stay lean.
        "current_state_snapshot": state_snapshot() if required else {"available": False, "reason": "turn not personal-required"},
        "review_alert": review_alert,
        "auto_review": auto_review,
        "policy": "receipt 是可校验事实：requires_personal_understanding=true 时，capture、finalize、session_check 缺一项即不得结束或声称已更新。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
