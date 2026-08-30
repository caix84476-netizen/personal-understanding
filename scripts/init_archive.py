"""Bootstrap a fresh Personal Understanding archive skeleton.

Creates the directory layout and the generic domain branches so that verbatim
captures, derived records, structural validation, and the session gate all work
from the very first message on a brand-new install.

Idempotent: existing files are never touched. Safe to run repeatedly.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH_TEMPLATES = ROOT / "templates" / "branches"

DIRS = (
    "memory",
    "memory/records",
    "memory/branches",
    "memory/v2",
    "memory/v2/traces",
    "sources",
    "sources/conversation",
    "sources/attachments",
    "backups",
)


def main() -> int:
    created: list[str] = []
    for rel in DIRS:
        path = ROOT / rel
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(rel + "/")
    if BRANCH_TEMPLATES.exists():
        for template in sorted(BRANCH_TEMPLATES.glob("*.md")):
            target = ROOT / "memory" / "branches" / template.name
            if not target.exists():
                shutil.copyfile(template, target)
                created.append("memory/branches/" + template.name)
    if created:
        print(f"init_archive: created {len(created)} entries:")
        for entry in created:
            print("  +", entry)
    else:
        print("init_archive: archive skeleton already present; nothing changed.")
    print("next: python scripts/install_mcp.py --auto   (then restart your client session)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
