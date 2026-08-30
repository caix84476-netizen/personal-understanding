#!/usr/bin/env python3
"""Close a capture only after records are linked or a concrete no-derivation reason is recorded."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
import subprocess
import sys
from pathlib import Path

from derivation_ledger import finalize_capture

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture-id", required=True)
    ap.add_argument("--disposition", choices=["derived", "no-derivation-needed"], required=True)
    ap.add_argument("--reason", default="")
    args = ap.parse_args()
    try:
        entry = finalize_capture(args.capture_id, args.disposition, args.reason, root=ROOT)
    except ValueError as exc:
        raise SystemExit(str(exc))
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_memory.py"), "--json", "--require-closed-captures"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(json.dumps({"status": "finalized", "capture": entry, "validation": json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else proc.stdout.strip()}, ensure_ascii=False, indent=2))
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
