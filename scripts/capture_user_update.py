#!/usr/bin/env python3
"""Capture a user personal-understanding update verbatim before derivation."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse, hashlib, json, subprocess, sys
from datetime import datetime
from pathlib import Path
from derivation_ledger import register_capture

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / "sources" / "conversation"
ID_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]+$")


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="the user's full verbatim message; UTF-8 text after shell escaping")
    source.add_argument("--file", help="UTF-8 file containing the user's full verbatim message")
    source.add_argument("--stdin", action="store_true", help="read the full verbatim message bytes from stdin; prefer this for very long messages to avoid command-line length limits")
    ap.add_argument("--capture-id", required=True)
    ap.add_argument("--conversation-id", default="")
    ap.add_argument("--captured-at", default="")
    ap.add_argument("--message-kind", default="personal-understanding-update")
    args = ap.parse_args()
    if not ID_RE.fullmatch(args.capture_id):
        raise SystemExit("capture-id may only use lowercase letters, digits, dots, underscores, and hyphens.")
    CAPTURES.mkdir(parents=True, exist_ok=True)
    txt = CAPTURES / f"{args.capture_id}.txt"
    meta_path = CAPTURES / f"{args.capture_id}.json"
    if txt.exists() or meta_path.exists():
        raise SystemExit(f"Refusing to overwrite an existing verbatim capture: {args.capture_id}")
    if args.file:
        raw = Path(args.file).read_bytes()
    elif args.stdin:
        raw = sys.stdin.buffer.read()
        if not raw:
            raise SystemExit("stdin contained no bytes; refusing to write an empty verbatim capture.")
    else:
        raw = str(args.text).encode("utf-8")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"Verbatim message must be UTF-8 text: {exc}")
    digest = hashlib.sha256(raw).hexdigest()
    txt.write_bytes(raw)
    verify = txt.read_bytes()
    if verify != raw:
        txt.unlink(missing_ok=True)
        raise SystemExit("Verbatim read-back check failed; write rolled back.")
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
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    register_capture(args.capture_id, source_path=meta["source_path"], captured_at=meta["captured_at"], message_kind=meta["message_kind"], content_sha256=digest, root=ROOT)
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "rebuild_views.py")], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        print("Verbatim capture saved, but the derived-view rebuild failed; the verbatim capture is not rolled back.", file=sys.stderr)
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode
    print(json.dumps({"status": "captured", "capture_id": args.capture_id, "path": meta["source_path"], "sha256": digest, "derivation_status": "pending", "view_rebuild": proc.stdout.strip(), "next_required_action": "create derived records, then finalize this capture"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
