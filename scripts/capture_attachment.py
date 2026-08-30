#!/usr/bin/env python3
"""Capture an attachment immutably, deduplicating exact binary matches."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import hashlib
import json
import mimetypes
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from derivation_ledger import ID_RE, register_capture

ROOT = Path(__file__).resolve().parents[1]
CONVERSATION = ROOT / "sources" / "conversation"
ATTACHMENTS = ROOT / "sources" / "attachments"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicate(source: Path, digest: str) -> Path | None:
    for folder in (ROOT / "sources" / "images", ATTACHMENTS):
        if not folder.exists():
            continue
        for candidate in folder.iterdir():
            if not candidate.is_file() or candidate.suffix.lower() == ".json":
                continue
            if candidate.stat().st_size == source.stat().st_size and sha256_file(candidate) == digest:
                return candidate
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    ap.add_argument("--capture-id", required=True)
    ap.add_argument("--conversation-id", default="")
    ap.add_argument("--captured-at", default="")
    ap.add_argument("--message-kind", default="attachment")
    args = ap.parse_args()
    if not ID_RE.fullmatch(args.capture_id):
        raise SystemExit("Invalid capture-id.")
    source = Path(args.file).resolve()
    if not source.is_file():
        raise SystemExit(f"Attachment not found: {source}")
    CONVERSATION.mkdir(parents=True, exist_ok=True)
    meta_path = CONVERSATION / f"{args.capture_id}.attachment.json"
    if meta_path.exists() or (CONVERSATION / f"{args.capture_id}.txt").exists():
        raise SystemExit(f"Refusing to overwrite an existing capture: {args.capture_id}")
    digest = sha256_file(source)
    duplicate = find_duplicate(source, digest)
    if duplicate:
        stored = duplicate
        deduplicated = True
    else:
        ATTACHMENTS.mkdir(parents=True, exist_ok=True)
        stored = ATTACHMENTS / f"{args.capture_id}{source.suffix.lower()}"
        shutil.copyfile(source, stored)
        if sha256_file(stored) != digest:
            stored.unlink(missing_ok=True)
            raise SystemExit("Attachment read-back hash check failed; write rolled back.")
        deduplicated = False
    mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    meta = {
        "capture_id": args.capture_id,
        "captured_at": args.captured_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "speaker": "user",
        "message_kind": args.message_kind,
        "conversation_id": args.conversation_id or None,
        "content_type": mime,
        "original_filename": source.name,
        "byte_length": source.stat().st_size,
        "sha256": digest,
        "immutable": True,
        "source_path": stored.relative_to(ROOT).as_posix(),
        "deduplicated_exact_binary": deduplicated,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    register_capture(args.capture_id, source_path=meta["source_path"], captured_at=meta["captured_at"], message_kind=meta["message_kind"], content_sha256=digest, root=ROOT)
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "rebuild_views.py")], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    result = {"status": "captured", "capture_id": args.capture_id, "source_path": meta["source_path"], "sha256": digest, "deduplicated_exact_binary": deduplicated, "derivation_status": "pending", "view_rebuild": proc.stdout.strip(), "next_required_action": "derive records or explicitly finalize as no-derivation-needed"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
