import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()


class V2ArchitectureTests(unittest.TestCase):
    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_preflight_is_model_router_with_v2_scheduler(self):
        result = self.run_script("preflight_context.py", "我感觉有点焦虑")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["activation"]["mode"], "model-decision")
        self.assertIn("v2", data)
        self.assertIn("followup_check", data["v2"])
        self.assertIn("archive_audit", data["v2"])
        self.assertNotIn("core", data)

    def test_short_interjection_still_has_v2_route(self):
        result = self.run_script("preflight_context.py", "唉")
        data = json.loads(result.stdout)
        self.assertEqual(data["preflight"]["mode"], "low-information")
        self.assertEqual(data["activation"]["mode"], "model-decision")
        self.assertEqual(data["v2"]["archive_audit"]["version"], "2.0.0")

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_current_state_has_core_conditions_examples_and_tensions(self):
        state = json.loads((ROOT / "memory" / "v2" / "current-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["version"], "2.0.0")
        for key in ("core", "conditions", "lived_examples", "tensions", "next"):
            self.assertIn(key, state)
        self.assertTrue(state["core"])
        self.assertTrue(state["conditions"])
        self.assertTrue(state["lived_examples"])

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_entities_keep_social_connections_and_facets(self):
        entities = [json.loads(line) for line in (ROOT / "memory" / "v2" / "entities.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        contexts = [json.loads(line) for line in (ROOT / "memory" / "v2" / "contexts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertTrue(entities, "requires at least one entity in the archive")
        # Every entity keeps its provenance links; do not assert on any personal entity id.
        self.assertTrue(all("record_refs" in item and "context_refs" in item for item in entities))
        self.assertTrue(any(item.get("kind") == "facet" for item in contexts))
        self.assertTrue(all(len(item.get("entity_ids", [])) >= 2 for item in contexts if item.get("kind") == "facet"))

    def test_capture_writer_rejects_overwrite(self):
        # Run against a temp captures dir so the real repository is never touched.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "capture.test.duplicate.txt").write_text("existing verbatim", encoding="utf-8")
            driver = f"""
import importlib.util, sys
from pathlib import Path
sys.path.insert(0, r"{SCRIPTS}")
spec = importlib.util.spec_from_file_location("cu_overwrite", r"{SCRIPTS / 'capture_user_update.py'}")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.CAPTURES = Path(r"{tmp}")
m.ROOT = Path(r"{tmp}")
sys.argv = ["capture_user_update.py", "--capture-id", "capture.test.duplicate", "--text", "不能覆盖"]
m.main()
"""
            result = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to overwrite", result.stderr + result.stdout)

    def test_followup_checker_has_contextual_contract(self):
        result = self.run_script("followup_check.py", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertIn("policy", data)
        self.assertIn("as_of", data)
        self.assertIn("due", data)
        self.assertIn("undated_pending", data)

    def test_mcp_exposes_v2_write_and_review_tools(self):
        payload = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n'
        result = subprocess.run([sys.executable, str(SCRIPTS / "mcp_server.py")], input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        names = {tool["name"] for tool in data["result"]["tools"]}
        self.assertTrue({"personal_capture_user_turn", "personal_add_followup", "personal_add_hypothesis", "personal_validate"}.issubset(names))


if __name__ == "__main__":
    unittest.main()
