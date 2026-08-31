#!/usr/bin/env python3
"""Capture a user personal-understanding update verbatim before derivation."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse, hashlib, json, subprocess, sys
from datetime import datetime
from pathlib import Path
from derivation_ledger import register_capture
from storage import atomic_write_bytes, atomic_write_text, mutation_lock
from turn_receipts import mark_captured, read_receipt

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / "sources" / "conversation"
ID_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]+$")


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="完整用户原话；命令行转义后的 UTF-8 文本")
    source.add_argument("--file", help="包含完整用户原话的 UTF-8 文件")
    source.add_argument("--stdin", action="store_true", help="从标准输入读取完整原话字节；超长消息优先用这个入口，避开命令行长度限制")
    ap.add_argument("--capture-id", required=True)
    ap.add_argument("--conversation-id", default="")
    ap.add_argument("--captured-at", default="")
    ap.add_argument("--message-kind", default="personal-understanding-update")
    ap.add_argument("--turn-id", default="", help="preflight 生成的 personal turn receipt；新 capture 必须绑定它")
    args = ap.parse_args()
    if not ID_RE.fullmatch(args.capture_id):
        raise SystemExit("capture-id 只能使用小写字母、数字、点、下划线和短横线。")
    txt = CAPTURES / f"{args.capture_id}.txt"
    meta_path = CAPTURES / f"{args.capture_id}.json"
    if args.file:
        raw = Path(args.file).read_bytes()
    elif args.stdin:
        raw = sys.stdin.buffer.read()
        if not raw:
            raise SystemExit("stdin 没有读到任何字节；拒绝写入空原话。")
    else:
        raw = str(args.text).encode("utf-8")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"原话必须是 UTF-8 文本：{exc}")
    digest = hashlib.sha256(raw).hexdigest()
    meta = {
        "capture_id": args.capture_id,
        "captured_at": args.captured_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "speaker": "user",
        "message_kind": args.message_kind,
        "conversation_id": args.conversation_id or None,
        "byte_length": len(raw),
        "utf8_sha256": digest,
        "codepoint_length": len(text),
        "immutable": True,
        "source_path": txt.relative_to(ROOT).as_posix(),
    }
    with mutation_lock(ROOT):
        if txt.exists() or meta_path.exists():
            raise SystemExit(f"Refusing to overwrite existing verbatim capture: {args.capture_id}")
        receipt = read_receipt(args.turn_id, ROOT) if args.turn_id else None
        if not receipt or not receipt.get("requires_personal_understanding"):
            raise SystemExit("必须先对完整当前消息运行 preflight_context.py，并提供该 turn-id；turn receipt 不存在或并非个人材料。")
        if receipt.get("message_sha256") != digest:
            raise SystemExit("capture 原话与 preflight 的完整当前消息不一致；拒绝截断或替换原话。")
        try:
            atomic_write_bytes(txt, raw)
            if txt.read_bytes() != raw:
                raise RuntimeError("原话回读校验失败")
            atomic_write_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
            register_capture(args.capture_id, source_path=meta["source_path"], captured_at=meta["captured_at"], message_kind=meta["message_kind"], content_sha256=digest, root=ROOT)
            if args.turn_id:
                mark_captured(args.turn_id, args.capture_id, ROOT)
        except Exception:
            meta_path.unlink(missing_ok=True)
            txt.unlink(missing_ok=True)
            raise
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "rebuild_views.py")], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        print("原话已保存，但派生视图重建失败；原话不会回滚。", file=sys.stderr)
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode
    print(json.dumps({"status": "captured", "capture_id": args.capture_id, "turn_id": args.turn_id or None, "path": meta["source_path"], "sha256": digest, "derivation_status": "pending", "view_rebuild": proc.stdout.strip(), "next_required_action": "create derived records, then finalize this capture"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
