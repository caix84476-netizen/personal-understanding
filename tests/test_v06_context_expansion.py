import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()
HAS_CATALOG = (ROOT / "memory" / "catalog.json").is_file()


class ContextExpansionV06Tests(unittest.TestCase):
    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *args], capture_output=True, text=True, encoding="utf-8")

    def seed_with_support(self):
        """Pick a record that has explicit supports so evidence promotion is exercised."""
        catalog_path = ROOT / "memory" / "catalog.json"
        if not catalog_path.is_file():
            self.skipTest("requires an initialized archive (memory/)")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        records = [item for item in catalog.get("records", []) if item.get("id")]
        if not records:
            self.skipTest("requires at least one record in the catalog")
        for item in records:
            supports = item.get("supports") or []
            if supports:
                return item["id"], supports[0]
        self.skipTest("requires a record with supports to exercise evidence promotion")

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_probe_treats_seed_as_starting_point_not_boundary(self):
        seed_id, support_id = self.seed_with_support()
        result = self.run_script(
            "retrieve_context.py", "--ids", seed_id, "--level", "probe", "--query", "我可能有点懒", "--max-context-candidates", "100",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        ids = {item["id"] for item in data["context_candidates"]}
        self.assertIn(support_id, ids)
        self.assertTrue(all("model_must_decide" in item for item in data["context_candidates"]))
        self.assertGreaterEqual(data["trace"]["scan"]["context_expansion"]["candidate_count"], len(data["context_candidates"]))
        self.assertIn("seed IDs are starting points", data["trace"]["scan"]["context_expansion"]["policy"])

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_deep_promotes_evidence_and_keeps_sources_out_of_probe(self):
        seed_id, support_id = self.seed_with_support()
        probe = self.run_script("retrieve_context.py", "--ids", seed_id, "--level", "probe")
        deep = self.run_script("retrieve_context.py", "--ids", seed_id, "--level", "deep")
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        self.assertEqual(deep.returncode, 0, deep.stdout + deep.stderr)
        probe_data = json.loads(probe.stdout)
        deep_data = json.loads(deep.stdout)
        self.assertFalse(probe_data["sources"])
        deep_ids = {item["id"] for item in deep_data["records"]}
        self.assertIn(support_id, deep_ids)
        self.assertIn(support_id, deep_data["trace"]["read"]["support_records"])

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_maintenance_keeps_history_separate_from_user_confirmation(self):
        result = self.run_script("maintenance_check.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Retained history", result.stdout)
        self.assertIn("Needs user confirmation", result.stdout)

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_query_only_call_can_make_seeds_but_still_exposes_context(self):
        result = self.run_script("retrieve_context.py", "--query", "大学前的压力", "--level", "probe")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data["read"]["records"])
        self.assertTrue(data["query_suggestions"])
        self.assertIn("context_candidates", data)
        self.assertEqual(data["read"]["level"], "probe")
        self.assertIn("must not implicitly count as read", data["trace"]["reason"])


if __name__ == "__main__":
    unittest.main()
