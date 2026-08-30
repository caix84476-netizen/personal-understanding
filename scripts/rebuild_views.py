#!/usr/bin/env python3
"""Rebuild simple views from Markdown frontmatter records."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()
from pathlib import Path

from catalog_utils import build_catalog, write_catalog
from v2_archive import build_archive

ROOT = Path(__file__).resolve().parents[1]


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data


def main() -> int:
    rows = []
    for path in sorted((ROOT / "memory" / "records").glob("*.md")):
        data = frontmatter(path)
        data["path"] = str(path.relative_to(ROOT)).replace("\\", "/")
        rows.append(data)
    current = [x for x in rows if x.get("status") == "current" or (x.get("kind") == "state" and x.get("status") == "uncertain")]
    index = ["# Memory Index", "", "Generated from `memory/records/`; do not treat this file as a source of truth.", ""]
    for row in rows:
        index.append(f"- `{row.get('id')}` [{row.get('kind')}, {row.get('status')}] — `{row.get('path')}`")
    (ROOT / "memory" / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")

    current_view = ["# Current State", "", "Generated view; verify before relying on dynamic state.", ""]
    for row in current:
        if row.get("kind") in {"state", "fact", "preference", "rule", "heuristic", "value", "decision", "model", "entity"}:
            current_view.append(f"- `{row.get('id')}`: {row.get('kind')} / confidence={row.get('confidence')} / source={row.get('source_refs')}")
    (ROOT / "memory" / "current.md").write_text("\n".join(current_view) + "\n", encoding="utf-8")

    timeline = ["# Timeline", "", "Generated view; event details defer to records and sources.", ""]
    for row in sorted(rows, key=lambda x: (x.get("valid_from") or x.get("last_confirmed") or "9999-99-99", x.get("id", ""))):
        if row.get("kind") in {"event", "decision"}:
            timeline.append(f"- {row.get('valid_from') or row.get('last_confirmed') or 'undated'} — `{row.get('id')}` — {row.get('status')}")
    (ROOT / "memory" / "timeline.md").write_text("\n".join(timeline) + "\n", encoding="utf-8")
    catalog = build_catalog()
    write_catalog(catalog)
    v2 = build_archive()
    print(f"Views rebuilt: {len(rows)} records, {len(current)} current records; catalog {catalog['counts']['records']} records / {catalog['counts']['sources']} sources; v2 timeline entries {v2['counts']['timeline_entries']} / entities {v2['counts']['entities']} / verbatim fragments {v2['verbatim_captures']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




