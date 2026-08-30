import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

HAS_ARCHIVE = (ROOT / "memory" / "v2" / "manifest.json").is_file()
HAS_CATALOG = (ROOT / "memory" / "catalog.json").is_file()


class DashboardSnapshotTests(unittest.TestCase):
    def make_snapshot(self):
        code = "import json,sys;sys.stdout.reconfigure(encoding='utf-8');from open_dashboard import snapshot;print(json.dumps(snapshot(),ensure_ascii=False))"
        result = subprocess.run([sys.executable, "-c", code], cwd=str(SCRIPTS), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    @unittest.skipUnless(HAS_ARCHIVE and HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_snapshot_keeps_private_and_source_material_visible(self):
        data = self.make_snapshot()
        rows = {item["id"]: item for item in data["records"]}
        self.assertTrue(rows)
        self.assertTrue(any(item["status"] == "current" for item in data["records"]))
        # Source material must stay visible; do not assert on any personal note.
        source_rows = [item for item in data["records"] if item.get("is_source_material")]
        self.assertTrue(source_rows, "source material must be visible in the snapshot")
        self.assertTrue(all("status" in item for item in source_rows))

    @unittest.skipUnless(HAS_ARCHIVE and HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_snapshot_exposes_source_groups_and_source_trace(self):
        data = self.make_snapshot()
        self.assertTrue(any(source.get("group") for source in data["sources"]))
        self.assertTrue(any(record["source_refs"] for record in data["records"]))
        self.assertTrue(any(source["record_ids"] for source in data["sources"]))

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_snapshot_exposes_v2_memory_surfaces(self):
        data = self.make_snapshot()
        self.assertEqual(data["v2"]["manifest"]["version"], "2.0.0")
        self.assertGreaterEqual(len(data["v2"]["events"]), 100)
        self.assertGreaterEqual(len(data["v2"]["entities"]), 20)
        self.assertGreaterEqual(len(data["v2"]["contexts"]), 20)
        self.assertIn("current_state", data["v2"])
        self.assertIn("audit", data["v2"])

    @unittest.skipUnless(HAS_ARCHIVE and HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_snapshot_keeps_replacement_chain_and_full_root_structure(self):
        data = self.make_snapshot()
        self.assertTrue(
            any(record.get("replaced_by") for record in data["records"]),
            "replacement chains must be exposed in the snapshot",
        )
        root_names = {item["name"] for item in data["root_structure"]}
        self.assertTrue({"memory", "sources", "references", "scripts", "tests", "dashboard"}.issubset(root_names))

    def test_tree_exposes_clickable_skill_directories(self):
        code = "import json,sys;sys.stdout.reconfigure(encoding='utf-8');from open_dashboard import tree;print(json.dumps(tree('references'),ensure_ascii=False))"
        result = subprocess.run([sys.executable, "-c", code], cwd=str(SCRIPTS), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["path"], "references")
        self.assertTrue(any(item["name"] == "retrieval-policy.md" and item["kind"] == "file" for item in data["items"]))

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_snapshot_is_read_only(self):
        before = (ROOT / "memory" / "catalog.json").stat().st_mtime_ns
        self.make_snapshot()
        self.assertEqual(before, (ROOT / "memory" / "catalog.json").stat().st_mtime_ns)

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_dashboard_is_audit_surface_and_redirects_are_exposed(self):
        data = self.make_snapshot()
        manifest = data["v2"]["manifest"]
        # Redirect structure must be exposed; do not assert on any personal alias target.
        self.assertIn("entity_redirects", manifest)
        for path in ["SKILL.md", "scripts/retrieve_v2.py", "scripts/validate_memory.py", "memory/v2/manifest.json"]:
            self.assertTrue((ROOT / path).exists(), path)

    def test_dashboard_has_single_clickable_entry_for_each_audit_surface(self):
        html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("nav-item", html)
        for token in ("data-view=\"diagnostics\"", "metricCard(\"timeline\"", "metricCard(\"entities\"", "metricCard(\"contexts\"", "metricCard(\"sources\""):
            self.assertTrue(token in html or token in js, token)
        self.assertIn("data-event", js)
        self.assertIn("data-entity", js)
        self.assertIn("data-context", js)
        self.assertIn("data-source", js)

    @unittest.skipUnless(shutil.which("node"), "node is required to syntax-check dashboard/app.js")
    def test_dashboard_javascript_parses_before_serving(self):
        result = subprocess.run(["node", "--check", str(ROOT / "dashboard" / "app.js")], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
