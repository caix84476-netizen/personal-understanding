"""Shared test fixture: a throwaway copy of the skill tree with a minimal valid archive.

Tests that exercise write paths (view rebuilds, review cycles, capture writes,
trace persistence) run against this temp copy so the real repository is never
modified by the test suite.
"""
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SKILL_MD = """---
name: personal-understanding
description: Minimal skill surface for offline tests.
version: 2.1.0
---

Test fixture skill body.
"""


def make_temp_repo(tmp_root: Path) -> Path:
    """Copy scripts/ into tmp_root and lay down a minimal valid archive skeleton.

    The result passes scripts/validate_memory.py, so scripts that gate on
    structural validation (rebuild, review cycle) run unchanged inside the copy.
    """
    shutil.copytree(
        REPO_ROOT / "scripts",
        tmp_root / "scripts",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for rel in (
        "references",
        "migrations",
        "memory",
        "memory/branches",
        "memory/records",
        "memory/v2",
        "sources",
        "sources/conversation",
    ):
        (tmp_root / rel).mkdir(parents=True, exist_ok=True)
    (tmp_root / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (tmp_root / "VERSION").write_text("2.1.0", encoding="utf-8")
    (tmp_root / "memory" / "branches" / "index.md").write_text("# Branches\n", encoding="utf-8")
    (tmp_root / "memory" / "v2" / "manifest.json").write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")
    (tmp_root / "memory" / "v2" / "current-state.json").write_text("{}", encoding="utf-8")
    return tmp_root


def write_record(root: Path, record_id: str, kind: str = "event", extra_lines: list[str] | None = None) -> Path:
    """Write one valid record into the temp archive; returns the record path."""
    folder = root / "memory" / "records"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {record_id}",
        f"kind: {kind}",
        "status: current",
        "confidence: high",
        "sensitivity: ordinary",
        "source_refs: sources/conversation/demo-capture.txt",
        *(extra_lines or []),
        "---",
        "",
        "Test record body.",
        "",
    ]
    path = folder / f"{record_id}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
