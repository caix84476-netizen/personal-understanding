import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()
HAS_CATALOG = (ROOT / "memory" / "catalog.json").is_file()


class SurveyV05Tests(unittest.TestCase):
    def run_script(self, name, *args):
        # Survey/catalog reads in tests are non-conversational maintenance reads;
        # the capture gate would otherwise reject them (§6.5 maintenance key).
        if name in ("retrieve_v2.py", "catalog_context.py"):
            args = ("--maintenance", *args)
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

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

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_survey_exposes_compact_v2_map_without_sources(self):
        result = self.run_script("catalog_context.py", "--view", "survey")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        # Survey is a routing map: it exposes counts and the v2 spine, never the
        # full legacy record list or raw source bodies.
        self.assertNotIn("sources", data)
        self.assertNotIn("survey", data)
        self.assertGreaterEqual(data["survey_counts"]["current"], 100)
        self.assertGreater(data["survey_counts"]["history"], 0)
        self.assertGreaterEqual(len(data["v2"]["spine"]), 50)
        self.assertGreaterEqual(len(data["v2"]["entities"]), 20)
        self.assertLess(len(result.stdout.encode("utf-8")), 200_000, "survey output must stay compact to avoid per-turn context blowup")
        self.assertTrue(data["v2"]["knowledge"], "knowledge rows must be exposed without asserting on personal ids")
        # Facets with a single shared entry are omitted from the map; probe
        # reconstructs them from entity pairs.
        self.assertTrue(all(item.get("entry_count", 0) >= 2 for item in data["v2"]["facets"]))

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_routing_view_still_exposes_full_current_map(self):
        result = self.run_script("catalog_context.py", "--view", "routing", "--query", "我可能有点懒")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        ids = {item["id"] for domain in data["domains"] for item in domain["records"]}
        self.assertTrue(ids, "routing view must expose the current record map")

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_spine_buckets_by_phase_without_recency_domination(self):
        # architecture-v2 promise: early-period key events are not pushed out of
        # the map by newer entries — per-phase representatives, not a time sort.
        result = self.run_script("catalog_context.py", "--view", "survey")
        data = json.loads(result.stdout)
        spine = data["v2"]["spine"]
        years = {(row.get("date_text") or "")[:4] for row in spine if (row.get("date_text") or "").strip()}
        self.assertGreaterEqual(len(years), 2, f"spine must span multiple years, got {sorted(years)}")
        self.assertNotIn("None", {row.get("phase") for row in spine}, "literal 'None' phase must be normalized to 未分期")

    def test_normalized_phase_treats_none_string_as_unphased(self):
        from v2_archive import normalized_phase
        self.assertEqual(normalized_phase("None"), "未分期")
        self.assertEqual(normalized_phase(None), "未分期")
        self.assertEqual(normalized_phase("  "), "未分期")
        self.assertEqual(normalized_phase("高中"), "高中")

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_chinese_query_returns_current_records(self):
        result = self.run_script("catalog_context.py", "--view", "routing", "--query", "我可能有点懒")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        ids = {item["id"] for domain in data["domains"] for item in domain["records"]}
        self.assertTrue(ids, "a Chinese query must match current records")
        self.assertTrue(all(isinstance(item, str) and item for item in ids))

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_probe_stops_before_raw_sources_and_deep_tracks_scan(self):
        seed_id, support_id = self.seed_with_support()
        probe = self.run_script("retrieve_context.py", "--ids", seed_id, "--level", "probe")
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        probe_data = json.loads(probe.stdout)
        self.assertEqual(probe_data["read"]["level"], "probe")
        self.assertFalse(probe_data["sources"])
        self.assertEqual(probe_data["trace"]["scan"]["phase"], "probe")
        self.assertGreaterEqual(probe_data["trace"]["scan"]["surveyed_current"], 1)

        deep = self.run_script("retrieve_context.py", "--ids", seed_id, "--level", "deep")
        self.assertEqual(deep.returncode, 0, deep.stdout + deep.stderr)
        deep_data = json.loads(deep.stdout)
        self.assertEqual(deep_data["trace"]["scan"]["phase"], "deep")
        self.assertIn(support_id, deep_data["trace"]["read"]["support_records"])

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_catalog_read_does_not_rewrite_generated_views(self):
        catalog = ROOT / "memory" / "catalog.json"
        records = json.loads(catalog.read_text(encoding="utf-8")).get("records", [])
        if not records:
            self.skipTest("requires at least one record in the catalog")
        before = catalog.stat().st_mtime_ns
        result = self.run_script("catalog_context.py", "--view", "survey")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(catalog.stat().st_mtime_ns, before)
        result = self.run_script("retrieve_context.py", "--ids", records[0]["id"], "--level", "probe")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(catalog.stat().st_mtime_ns, before)

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_full_catalog_contains_conflict_and_replacement_fields(self):
        result = self.run_script("catalog_context.py", "--view", "full")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        for item in data["records"]:
            self.assertIn("contradicts", item)
            self.assertIn("supersedes", item)

    @unittest.skipUnless(HAS_CATALOG, "requires an initialized archive (memory/)")
    def test_trace_contains_transition_and_evidence_gap_fields(self):
        seed_id, _ = self.seed_with_support()
        result = self.run_script("retrieve_context.py", "--ids", seed_id, "--level", "probe")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        trace = json.loads(result.stdout)["trace"]
        self.assertIn("candidate_transitions", trace["scan"])
        self.assertIn("hypotheses", trace["uncertainty"])
        self.assertIn("evidence_gaps", trace["uncertainty"])


if __name__ == "__main__":
    unittest.main()
