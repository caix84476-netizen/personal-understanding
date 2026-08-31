#!/usr/bin/env python3
"""Rebuild simple views from Markdown frontmatter records."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()
from pathlib import Path

from catalog_utils import build_catalog, write_catalog
from v2_archive import build_archive
from storage import atomic_write_text, mutation_lock

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
    # v2 page cleanup and catalog projections are all regenerateable, but two
    # agents rebuilding them concurrently used to delete each other's output.
    with mutation_lock(ROOT):
        rows = []
        for path in sorted((ROOT / "memory" / "records").glob("*.md")):
            data = frontmatter(path)
            data["path"] = str(path.relative_to(ROOT)).replace("\\", "/")
            rows.append(data)
        current = [x for x in rows if x.get("status") == "current" or (x.get("kind") == "state" and x.get("status") == "uncertain")]
        index = ["# 记忆索引", "", "由 `memory/records/` 生成；不要把本文件当成事实源。", ""]
        for row in rows: index.append(f"- `{row.get('id')}` [{row.get('kind')}, {row.get('status')}] — `{row.get('path')}`")
        atomic_write_text(ROOT / "memory" / "index.md", "\n".join(index) + "\n")
        current_view = ["# 当前状态", "", "生成视图；使用动态状态前请确认。", ""]
        for row in current:
            if row.get("kind") in {"state", "fact", "preference", "rule", "heuristic", "value", "decision", "model", "entity"}: current_view.append(f"- `{row.get('id')}`: {row.get('kind')} / confidence={row.get('confidence')} / source={row.get('source_refs')}")
        atomic_write_text(ROOT / "memory" / "current.md", "\n".join(current_view) + "\n")
        timeline = ["# 时间线", "", "生成视图；事件详情仍以记录和来源为准。", ""]
        for row in sorted(rows, key=lambda x: (x.get("valid_from") or x.get("last_confirmed") or "9999-99-99", x.get("id", ""))):
            if row.get("kind") in {"event", "decision"}: timeline.append(f"- {row.get('valid_from') or row.get('last_confirmed') or 'undated'} — `{row.get('id')}` — {row.get('status')}")
        atomic_write_text(ROOT / "memory" / "timeline.md", "\n".join(timeline) + "\n")
        catalog = build_catalog(); write_catalog(catalog); v2 = build_archive()
    print(f"视图已重建： {len(rows)} 条记录，{len(current)} 条当前记录；目录 {catalog['counts']['records']} 条记录/{catalog['counts']['sources']} 个来源；v2 时间条目 {v2['counts']['timeline_entries']} / 实体 {v2['counts']['entities']} / 原话片段 {v2['verbatim_captures']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




