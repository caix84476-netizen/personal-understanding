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
HAS_CATALOG = (ROOT / "memory" / "catalog.json").is_file()


class RetrievalV2Tests(unittest.TestCase):
    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_catalog_survey_is_v2_memory_map_without_raw_sources(self):
        result = self.run_script("catalog_context.py", "--view", "survey", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["catalog_version"], "2.0.0")
        self.assertIn("v2", data)
        self.assertGreaterEqual(len(data["v2"]["spine"]), 50)
        self.assertGreaterEqual(len(data["v2"]["entities"]), 20)
        self.assertGreaterEqual(len(data["v2"]["facets"]), 20)
        self.assertNotIn("sources", data)
        self.assertNotIn("verbatim", data["v2"]["spine"][0])

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_v2_probe_does_not_load_fragments(self):
        result = self.run_script("retrieve_v2.py", "--query", "高中 足球", "--level", "probe", "--no-trace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["retrieval_version"], "2.0.0")
        self.assertEqual(data["read"]["level"], "probe")
        self.assertFalse(data["fragments"])
        self.assertTrue(data["timeline"] or data["entities"] or data["facets"])
        self.assertIn("stopped", data["trace"])

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_v2_deep_reads_selected_fragments_and_preserves_fidelity(self):
        result = self.run_script("retrieve_v2.py", "--query", "个人理解 2.0 原话", "--level", "deep", "--no-trace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["fragments"])
        fidelities = {item["fidelity"] for item in data["fragments"]}
        self.assertIn("verbatim", fidelities)
        self.assertTrue(fidelities <= {"verbatim", "summary_only"})
        self.assertTrue(data["knowledge"])

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_legacy_retrieval_remains_compatible(self):
        catalog = json.loads((ROOT / "memory" / "catalog.json").read_text(encoding="utf-8"))
        records = [item for item in catalog.get("records", []) if item.get("id")]
        self.assertTrue(records, "requires at least one record in the catalog")
        result = self.run_script("retrieve_context.py", "--ids", records[0]["id"], "--level", "probe")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["read"]["level"], "probe")
        self.assertFalse(data["sources"])

    def test_rebuild_is_repeatable_and_emits_v2(self):
        # Rebuild writes derived views, so run it inside a temp copy of the skill tree.
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fixture.make_temp_repo(Path(tmp))
            for _ in range(2):
                result = subprocess.run([sys.executable, str(repo / "scripts" / "rebuild_views.py")], capture_output=True, text=True, encoding="utf-8", errors="replace")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("v2", result.stdout)
            manifest = json.loads((repo / "memory" / "v2" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "2.0.0")


if __name__ == "__main__":
    unittest.main()
