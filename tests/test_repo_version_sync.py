"""Repo self-check: SKILL.md / SKILL.zh-CN.md / VERSION / pyproject must agree.

The 2.2.0 release bumped SKILL.md + VERSION but not validate_memory.py's
hardcoded expectation, so installs failed validation out of the box. This test
pins all four version declarations together so a partial bump fails CI.
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
        self.assertEqual(frontmatter_version(REPO / "SKILL.zh-CN.md"), version_file)
        self.assertEqual(m.group(1), version_file)


if __name__ == "__main__":
    unittest.main()
