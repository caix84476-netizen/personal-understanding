import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()
HAS_SOURCES = (ROOT / "sources").is_dir()


class ArchiveV2Tests(unittest.TestCase):
    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_validator_reports_real_state_not_fake_pass(self):
        result = self.run_script("validate_memory.py", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["version"], "2.1.0")
        self.assertIn(data["status"], {"clean", "warnings"})
        self.assertGreaterEqual(len(data["warnings"]), 1)
        strict = self.run_script("validate_memory.py", "--strict")
        self.assertNotEqual(strict.returncode, 0)
        self.assertIn("warning", strict.stdout)

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_v2_manifest_and_views_exist(self):
        manifest = json.loads((ROOT / "memory" / "v2" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "2.0.0")
        self.assertGreaterEqual(manifest["counts"]["timeline_entries"], 100)
        self.assertGreaterEqual(manifest["counts"]["entities"], 20)
        self.assertGreaterEqual(manifest["counts"]["contexts"], 20)
        self.assertGreaterEqual(manifest["counts"]["knowledge"], 30)
        for name in ("fragments.jsonl", "timeline.jsonl", "entities.jsonl", "contexts.jsonl", "followups.jsonl", "hypotheses.jsonl", "relations.jsonl", "knowledge.jsonl", "current-state.json", "index.json"):
            self.assertTrue((ROOT / "memory" / "v2" / name).exists(), name)

    @unittest.skipUnless(HAS_ARCHIVE and HAS_SOURCES, "requires an initialized archive (memory/ and sources/)")
    def test_verbatim_capture_is_immutable_and_hashed(self):
        # Pick whichever capture is on disk instead of asserting on a personal one.
        captures = sorted((ROOT / "sources" / "conversation").glob("*.txt"))
        self.assertTrue(captures, "requires at least one verbatim capture under sources/conversation/")
        text_path = captures[0]
        meta_path = text_path.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw = text_path.read_bytes()
        self.assertEqual(meta["utf8_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertTrue(meta["immutable"])
        fragments = [json.loads(line) for line in (ROOT / "memory" / "v2" / "fragments.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        capture = next(item for item in fragments if item["id"] == f"fragment.capture.{text_path.stem}")
        self.assertEqual(capture["fidelity"], "verbatim")
        self.assertEqual(capture["verbatim_sha256"], hashlib.sha256(capture["verbatim"].encode("utf-8")).hexdigest())

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_old_records_are_preserved_as_legacy_debt(self):
        fragments = [json.loads(line) for line in (ROOT / "memory" / "v2" / "fragments.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if not any(item["fidelity"] == "summary_only" for item in fragments):
            self.skipTest("requires a migrated legacy archive with summary-only fragments")
        # Legacy v0.x records must survive the migration; do not assert on any personal id.
        legacy_records = list((ROOT / "memory" / "records").glob("*.md"))
        self.assertTrue(legacy_records, "legacy records must be preserved under memory/records/")
        review = self.run_script("review_v2.py", "--deep", "--json")
        data = json.loads(review.stdout)
        self.assertTrue(any(item.get("code") == "summary-only-debt" for item in data["warnings"]))

    @unittest.skipUnless(HAS_SOURCES, "requires source material (sources/)")
    def test_sources_and_legacy_views_remain_available(self):
        self.assertGreaterEqual(len(list((ROOT / "sources" / "markdown").glob("*.md"))), 22)
        self.assertGreaterEqual(len(list((ROOT / "sources" / "images").glob("*.jpg"))), 5)
        self.assertGreaterEqual(len(list((ROOT / "sources" / "ocr").glob("*.md"))), 5)
        timeline_text = (ROOT / "memory" / "timeline.md").read_text(encoding="utf-8")
        self.assertTrue(timeline_text.strip(), "legacy timeline view must not be empty")

    def test_v2_policy_surface_is_complete(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in ("verbatim fidelity", "memory-weight axis", "Entity profiles", "Context cards", "Follow-ups and proactive check-ins", "causal interpretation layer", "Deep review and structural validation"):
            self.assertIn(phrase, skill)
        for name in ("architecture-v2.md", "capture-and-verbatim-policy.md", "timeline-and-followup-policy.md", "entity-and-context-policy.md", "causal-hypothesis-policy.md"):
            self.assertTrue((ROOT / "references" / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
