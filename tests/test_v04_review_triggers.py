import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()
HAS_SOURCES = (ROOT / "sources").is_dir()


class ReviewTriggerV2Tests(unittest.TestCase):
    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_preflight_reports_review_alert_on_correction(self):
        result = self.run_script("preflight_context.py", "普通任务", "--immediate-reason", "correction")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["auto_review"]["triggered"])
        self.assertEqual(data["auto_review"]["reason"], "correction")
        self.assertIn("alerts", data["auto_review"])

    def test_preflight_without_trigger_does_not_emit_alert(self):
        result = self.run_script("preflight_context.py", "普通技术问题")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data["auto_review"]["triggered"])
        self.assertNotIn("alerts", data["auto_review"])

    def test_review_policy_documents_v2_boundaries(self):
        policy = (ROOT / "references" / "review-and-feedback-loops.md").read_text(encoding="utf-8")
        for phrase in ("Deep review is automatic", "verbatim", "model guesses", "Delete user verbatim", "semantic-review-required"):
            self.assertIn(phrase, policy)

    @unittest.skipUnless(HAS_ARCHIVE and HAS_SOURCES, "requires an initialized archive (memory/ and sources/)")
    def test_review_report_exposes_semantic_boundary(self):
        result = self.run_script("review_skill.py", "--deep", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertIn("audit-only", data["mutation"])
        self.assertIn("proposed_actions", data["approval"])
        self.assertFalse(data["approval"]["required_for_content_changes"])


if __name__ == "__main__":
    unittest.main()
