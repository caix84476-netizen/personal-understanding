#!/usr/bin/env python3
"""Create the mandatory, durable routing receipt before a user-turn answer."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse, json, sys
from pathlib import Path
from followup_check import check_followups
from turn_receipts import classify_personal_turn, create_receipt

ROOT = Path(__file__).resolve().parents[1]

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
    ap.add_argument("--conversation-id", default="")
    ap.add_argument("--budget", type=int, default=4000, help="兼容旧调用；不影响 receipt")
    ap.add_argument("--immediate-reason", choices=["correction", "attribution", "privacy", "structure", "compression", "decision"])
    args = ap.parse_args()
    source_count = int(args.text is not None) + int(bool(args.file)) + int(bool(args.stdin))
    if source_count != 1:
        ap.error("必须且只能提供 text、--file 或 --stdin 之一")
    text = _read(args)
    receipt = create_receipt(text, turn_id=args.turn_id or None, conversation_id=args.conversation_id or None, root=ROOT)
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
        "review_alert": review_alert,
        "auto_review": auto_review,
        "policy": "receipt 是可校验事实：requires_personal_understanding=true 时，capture、finalize、session_check 缺一项即不得结束或声称已更新。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
