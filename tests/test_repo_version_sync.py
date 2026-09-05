"""Repo self-check: SKILL.md / SKILL.zh-CN.md / VERSION / pyproject / README×2 /
CHANGELOG head must all agree.

The 2.2.0 release bumped SKILL.md + VERSION but not validate_memory.py's
hardcoded expectation, so installs failed validation out of the box. The 2.4.1
audit noted the old four-way pin let README and the CHANGELOG drift unseen, so
the 2.5.0 release pins them too: a partial version bump now fails CI everywhere.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def frontmatter_version(path: Path) -> str:
    m = re.search(r"^version:\s*(\S+)\s*$", path.read_text(encoding="utf-8-sig"), re.M)
    return m.group(1) if m else ""


class RepoVersionSyncTests(unittest.TestCase):
    def test_all_version_declarations_agree(self):
        version_file = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
        self.assertTrue(version_file, "VERSION file missing or empty")
        self.assertIsNotNone(m, "pyproject.toml missing project.version")
        self.assertEqual(frontmatter_version(REPO / "SKILL.md"), version_file)
        # 2.6.0: SKILL.zh-CN.md removed — the skill brain is Chinese-native and
        # the duplicated shadow drifted (453 vs 451 lines) while pinning CI releases.
        self.assertEqual(m.group(1), version_file)
        en = re.search(r"\*\*Current release: v([0-9.]+)\*\*", (REPO / "README.md").read_text(encoding="utf-8"))
        zh = re.search(r"\*\*当前版本：v([0-9.]+)\*\*", (REPO / "README.zh-CN.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(en, "README.md current-release line missing")
        self.assertIsNotNone(zh, "README.zh-CN.md current-release line missing")
        self.assertEqual(en.group(1), version_file)
        self.assertEqual(zh.group(1), version_file)
        head = re.search(r"^## (\d+\.\d+\.\d+)", (REPO / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(head, "CHANGELOG has no version heading")
        self.assertEqual(head.group(1), version_file)


if __name__ == "__main__":
    unittest.main()
