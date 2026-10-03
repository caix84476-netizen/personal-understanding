#!/usr/bin/env python3
"""Crash-safe view staleness detection + rebuild-on-read (2.7.0).

Write tools no longer rebuild inline. A full catalog+v2 rebuild per write made
every turn pay ~6s and — under concurrency — let the post-write validate race
other writers, so successful writes came back isError (fake failures that
coerced blind retries). Writes now just leave an mtime trail; the first read
after them pays one rebuild under the lock. There is no dirty-flag file on
purpose: mtimes cannot disagree with what actually landed on disk, so a crash
between write and rebuild can never strand a stale flag or trigger a spurious
rebuild. Shared by the MCP server and session_check so both see the same
freshness line.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from storage import mutation_lock


def rebuild_sources(root: Path) -> list[Path]:
    """Files writes touch that derived views are built from.

    followups/hypotheses jsonl are deliberately NOT sources: _build_archive
    rewrites them itself (importing open-loops seeds), so counting them as
    sources made every rebuild newer than catalog.json — views_stale could
    never go false again, and every read paid a full rebuild forever. They are
    also read LIVE by catalog/retrieve (load_v2 reads the jsonl directly), so
    writes to them never need a projection refresh in the first place."""
    return (
        list((root / "memory" / "records").glob("*.md"))
        + list((root / "sources" / "conversation").glob("*.json"))
        + list((root / "sources" / "images").glob("*.json"))
    )


def rebuild_outputs(root: Path) -> list[Path]:
    return [
        root / "memory" / "catalog.json",
        root / "memory" / "v2" / "manifest.json",
        root / "memory" / "v2" / "entities.jsonl",
        root / "memory" / "v2" / "timeline.jsonl",
    ]


def views_stale(root: Path) -> bool:
    sources = rebuild_sources(root)
    if not sources:
        return False
    newest_source = max(path.stat().st_mtime for path in sources)
    oldest_output = min((path.stat().st_mtime for path in rebuild_outputs(root) if path.exists()), default=0.0)
    return newest_source > oldest_output


def ensure_fresh_views(root: Path, runner: Callable[[str, list[str]], tuple[int, str]]) -> tuple[bool, str]:
    """Rebuild once if stale. ``runner(name, args) -> (code, output)`` is injected
    so the MCP server passes its subprocess wrapper and CLI callers pass theirs.
    Raises RuntimeError when the rebuild fails — data is intact, views are just
    old; callers decide whether that blocks their answer.

    2.7.0 hotfix: the double-checked lock originally WRAPPED the rebuild — a
    guaranteed deadlock, because rebuild_views.py takes the same cross-process
    file lock: the parent held it while blocking on the child, the child waited
    for the lock, and both sat there until the subprocess timeout. The first
    MCP read after any write could therefore never succeed. The child owns the
    lock now (it locks internally); concurrent first-readers serialize behind
    each other's rebuild, which is idempotent, and a write landing mid-rebuild
    simply leaves the views stale for the NEXT read."""
    if not views_stale(root):
        return False, ""
    code, output = runner("rebuild_views.py", [])
    if code != 0:
        raise RuntimeError(f"视图重建失败（写入的数据本身完好，读取的是旧投影）：{output}")
    return True, output
