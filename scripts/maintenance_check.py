#!/usr/bin/env python3
"""Print a read-only maintenance report; never mutates the archive."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()
from datetime import date
from pathlib import Path
from collections import defaultdict
import hashlib
import re
import json
from v2_archive import v2_audit, load_v2
from followup_check import check_followups

ROOT = Path(__file__).resolve().parents[1]
TODAY = date.today()


def parse(path: Path) -> tuple[dict[str, str], str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    data = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                body_start = i + 1
                break
            if ":" in line:
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip()
    return data, " ".join(x.strip() for x in lines[body_start:] if x.strip())


def main() -> int:
    records = []
    fingerprints = defaultdict(list)
    for path in sorted((ROOT / "memory" / "records").glob("*.md")):
        meta, body = parse(path)
        meta["path"] = str(path.relative_to(ROOT))
        records.append(meta)
        normalized = re.sub(r"\s+", " ", body).casefold()
        if normalized:
            fingerprints[hashlib.sha256(normalized.encode("utf-8")).hexdigest()].append(path.name)
    print("Maintenance report (read-only)")
    print(f"Record count: {len(records)}")
    historical = [data for data in records if data.get("status") in {"superseded", "archived"}]
    uncertain = [data for data in records if data.get("status") == "uncertain"]
    if historical:
        archived = sum(1 for data in historical if data.get("status") == "archived")
        superseded = len(historical) - archived
        print(f"Retained history: {len(historical)} entries (archived {archived}; superseded {superseded}). These are readable history, not pending fixes.")
    for data in uncertain:
        print(f"- Needs user confirmation: {data.get('id')} [uncertain] ({data.get('path')})")
    for data in records:
        confirmed = data.get("last_confirmed")
        if confirmed and re.match(r"^\d{4}-\d{2}-\d{2}$", confirmed):
            age = (TODAY - date.fromisoformat(confirmed)).days
            if age > 180 and data.get("status") == "current":
                print(f"- Stale check: {data.get('id')} last_confirmed={confirmed} age_days={age}")
    for names in fingerprints.values():
        if len(names) > 1:
            print(f"- Duplicate body candidates: {', '.join(names)}")
    inbox = ROOT / "memory" / "inbox.md"
    if inbox.exists():
        pending = [line for line in inbox.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]
        print(f"Pending review candidates: {len(pending)}")
    v2 = v2_audit()
    followups = check_followups()
    manifest = load_v2().get("manifest", {})
    print(f"v2: {manifest.get('version', 'missing')}; timeline entries {manifest.get('counts', {}).get('timeline_entries', 0)}; entities {manifest.get('counts', {}).get('entities', 0)}; context cards {manifest.get('counts', {}).get('contexts', 0)}")
    print(f"v2 validation: {v2.get('status')}; errors {len(v2.get('errors', []))}; warnings {len(v2.get('warnings', []))}")
    print(f"Follow-ups: due {len(followups.get('due', []))}; upcoming {len(followups.get('upcoming', []))}; missing date {len(followups.get('undated_pending', []))}")
    return 1 if v2.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

