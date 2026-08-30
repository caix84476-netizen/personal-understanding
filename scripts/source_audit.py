#!/usr/bin/env python3
"""Audit source_refs so provenance gaps cannot masquerade as missing evidence."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
from pathlib import Path
from typing import Any

from catalog_utils import ROOT, load_records, parse_frontmatter, source_ref_matches, source_files, split_ids

CONVERSATION_REFS = {"current-conversation", "current_conversation"}


def known_file_refs() -> list[str]:
    """Return repo-relative file paths that may legitimately appear in source_refs."""
    roots = [ROOT / "sources", ROOT / "memory", ROOT / "references"]
    refs: list[str] = []
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                refs.append(path.relative_to(ROOT).as_posix())
    # Include source paths through the canonical source enumerator too; this keeps
    # the audit aligned with catalog construction if source folders change.
    for path in source_files():
        refs.append(path.relative_to(ROOT).as_posix())
    return sorted(set(refs))


def classify_ref(ref: str, record_ids: set[str], file_refs: list[str]) -> str:
    if ref in CONVERSATION_REFS:
        return "conversation"
    if ref in record_ids:
        return "record"
    if Path(ref).is_absolute() and Path(ref).exists():
        return "file"
    if any(source_ref_matches(ref, candidate) for candidate in file_refs):
        return "file"
    return "unresolved"


def audit_records() -> list[dict[str, Any]]:
    rows = load_records()
    record_ids = {row["meta"].get("id", "") for row in rows}
    file_refs = known_file_refs()
    issues: list[dict[str, Any]] = []
    for row in rows:
        meta = row["meta"]
        unresolved = []
        classifications = {}
        for ref in split_ids(meta.get("source_refs")):
            kind = classify_ref(ref, record_ids, file_refs)
            classifications[ref] = kind
            if kind == "unresolved":
                unresolved.append(ref)
        if unresolved:
            issues.append({
                "id": meta.get("id"),
                "kind": meta.get("kind"),
                "status": meta.get("status"),
                "confidence": meta.get("confidence"),
                "unresolved_refs": unresolved,
                "classifications": classifications,
                "path": str(row["path"]),
            })
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true", help="fail when unresolved source_refs are found")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    issues = audit_records()
    if args.json:
        print(json.dumps({"unresolved_source_refs": issues, "count": len(issues)}, ensure_ascii=False, indent=2))
    else:
        if issues:
            print(f"{len(issues)} record(s) have unresolved source_refs:")
            for item in issues:
                print(f"- {item['id']} [{item['status']}/{item['confidence']}]: {', '.join(item['unresolved_refs'])}")
        else:
            print("All source_refs resolved.")
    return 1 if args.strict and issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
