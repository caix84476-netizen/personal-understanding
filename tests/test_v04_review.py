import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fixture

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()
HAS_SOURCES = (ROOT / "sources").is_dir()


class ReviewV2Tests(unittest.TestCase):
    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_deep_review_reports_nontrivial_risks(self):
        result = self.run_script("review_v2.py", "--deep", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["review_version"], "2.0.0")
        self.assertEqual(data["status"], "warnings")
        self.assertGreaterEqual(data["summary"]["warnings"], 1)
        self.assertGreaterEqual(data["sections"]["provenance"]["summary_only_fragments"], 100)
        self.assertGreaterEqual(data["sections"]["entities"]["context_cards"], 20)
        self.assertIn("semantic_review_contract", data)

    @unittest.skipUnless(HAS_ARCHIVE and HAS_SOURCES, "requires an initialized archive (memory/ and sources/)")
    def test_legacy_review_includes_v2_status(self):
        result = self.run_script("review_skill.py", "--deep", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertIn("v2_status", data["summary"])
        self.assertIn("v2", data["audit"])
        self.assertIn(data["summary"]["v2_status"], {"clean", "warnings", "failed"})

    def test_review_cycle_keeps_semantic_review_boundary(self):
        # The review cycle rebuilds views and can write review state, so it runs
        # inside a temp copy of the skill tree instead of the real repository.
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fixture.make_temp_repo(Path(tmp))
            result = subprocess.run([sys.executable, str(repo / "scripts" / "run_review_cycle.py"), "--reason", "structure", "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data["infrastructure_ok"])
            self.assertTrue(data["requires_semantic_review"])
            self.assertFalse(data["state_reset"])
            self.assertIn("v2_review", data)

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_strict_validator_fails_on_migration_warnings(self):
        result = self.run_script("validate_memory.py", "--strict")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("warning", result.stdout)


if __name__ == "__main__":
    unittest.main()
