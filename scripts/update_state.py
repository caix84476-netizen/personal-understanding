#!/usr/bin/env python3
"""Preview or apply a new version of a dynamic state record.

Default is dry-run. Use --apply only after reviewing the proposed change.
"""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()
import argparse
from datetime import datetime
from pathlib import Path
import re

from source_audit import audit_records

ROOT = Path(__file__).resolve().parents[1]


def parse(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    data: dict[str, str] = {}
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" in line:
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip()
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--id", required=True, help="ID of an existing state record")
    ap.add_argument("--content", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--confidence", choices=["very-high", "high", "medium-high", "medium", "low-medium", "low"], default="medium")
    ap.add_argument("--valid-from")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-unresolved-source", action="store_true", help="only for explicit historical source migration")
    args = ap.parse_args()
    records_dir = ROOT / "memory" / "records"
    matches = []
    for path in records_dir.glob("*.md"):
        meta = parse(path)
        if meta.get("id") == args.id:
            matches.append((path, meta))
    if not matches:
        raise SystemExit(f"No record found for id: {args.id}")
    path, old = matches[0]
    if old.get("kind") != "state":
        raise SystemExit(f"Only state records can be versioned by this command: {old.get('kind')}")
    # Hard gate: the source of a new state version must resolve to a real
    # capture or file. "Just write it" is how unanchored drift starts.
    source_resolved = (ROOT / args.source).exists()
    if not source_resolved and not args.allow_unresolved_source:
        raise SystemExit(
            f"Write blocked: source does not exist: {args.source}. Save the verbatim capture or attachment first with "
            "capture_user_update.py / capture_attachment.py, or use --allow-unresolved-source for an explicit historical migration."
        )
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    new_id = f"{args.id}.{stamp}"
    new_path = records_dir / f"{new_id}.md"
    carried = []
    for field in ("domain", "parent_ids", "related_ids", "applies_when"):
        if old.get(field):
            carried.append(f"{field}: {old[field]}")
    carried_text = ("\n" + "\n".join(carried)) if carried else ""
    content = f"""---\nid: {new_id}\nkind: state\nvalid_from: {args.valid_from or datetime.now().date().isoformat()}\nlast_confirmed: {datetime.now().date().isoformat()}\nstatus: current\nconfidence: {args.confidence}\nsensitivity: {old.get('sensitivity', 'private')}\nsource_refs: {args.source}\nsupersedes: {args.id}{carried_text}\n---\n\n{args.content}\n"""
    issue = next((item for item in audit_records() if item["id"] == args.id), None)
    if args.apply and issue and not args.allow_unresolved_source:
        raise SystemExit(
            "State update blocked: the old record has unresolved source_refs "
            + ", ".join(issue["unresolved_refs"])
            + "; fix the sources first or explicitly pass --allow-unresolved-source."
        )

    print("Proposed state update")
    print(f"- Old record: {path.name}")
    print(f"- New record: {new_path.name}")
    print(f"- Content: {args.content}")
    if not args.apply:
        print("Dry run: no files modified; review and rerun with --apply")
        return 0
    old_text = path.read_text(encoding="utf-8")
    old_text = re.sub(r"^status: (?:current|uncertain)\s*$", "status: superseded", old_text, count=1, flags=re.MULTILINE)
    path.write_text(old_text, encoding="utf-8")
    new_path.write_text(content, encoding="utf-8")
    print("Applied: old record superseded and new version created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


