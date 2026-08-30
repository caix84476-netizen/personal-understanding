"""Regression tests for the 2026-08-28 structural round:
salience decay, hard session gate, and the answer feedback loop."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()


class SalienceReviewTests(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "salience_review.py"), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

    def test_real_repo_dry_run_reports_without_writing(self):
        result = self._run("--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["mode"], "dry-run")
        self.assertIsInstance(data["candidates"], int)

    def test_apply_writes_explicit_salience_and_reviewed_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / "memory" / "records"
            records.mkdir(parents=True)
            record = records / "event.test.old-mention.md"
            record.write_text(
                "\n".join([
                    "---",
                    "id: event.test.old-mention",
                    "kind: event",
                    "status: current",
                    "confidence: high",
                    "sensitivity: ordinary",
                    "source_refs: current-conversation",
                    "last_confirmed: 2025-01-01",
                    "---",
                    "",
                    "很久以前的事件。",
                    "",
                ]),
                encoding="utf-8",
            )
            driver = f"""
import importlib.util, sys
from pathlib import Path
sys.path.insert(0, r"{SCRIPTS}")
import catalog_utils
spec = importlib.util.spec_from_file_location("sr", r"{SCRIPTS / 'salience_review.py'}")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.ROOT = Path(r"{root}")
catalog_utils.ROOT = Path(r"{root}")
rows = m.candidates(180, root=Path(r"{root}"))
assert len(rows) == 1, rows
assert m.apply_decay(rows[0], root=Path(r"{root}"))
sys.exit(0)
"""
            result = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = record.read_text(encoding="utf-8")
            self.assertIn("salience: 0", text)
            self.assertIn("salience_reviewed: ", text)
            self.assertIn("很久以前的事件。", text)


class SessionGateTests(unittest.TestCase):
    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_gate_passes_on_current_repo(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "session_check.py"), "--allow-warnings"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["may_claim_memory_updated"])
        self.assertFalse(data["hard_fail"])

    def test_gate_reports_pending_captures_as_hard_fail(self):
        spec = importlib.util.spec_from_file_location("sc", SCRIPTS / "session_check.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        fake_validate = {"status": "warnings", "errors": [], "warnings": ["x"], "derivation": {"pending_capture_ids": ["capture.test.pending"]}, "v2": {"status": "warnings"}}
        original = module.run
        try:
            module.run = lambda name, *args: (0, fake_validate) if name == "validate_memory.py" else original(name, *args)
            import contextlib, io
            buffer = io.StringIO()
            old_argv = sys.argv
            sys.argv = ["session_check.py", "--allow-warnings"]
            try:
                with contextlib.redirect_stdout(buffer):
                    code = module.main()
            finally:
                sys.argv = old_argv
        finally:
            module.run = original
        self.assertEqual(code, 1)
        output = json.loads(buffer.getvalue())
        self.assertFalse(output["may_claim_memory_updated"])
        self.assertIn("capture.test.pending", output["gates"]["closed_captures"]["pending"])


class FeedbackLoopTests(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "record_feedback.py"), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

    def test_real_repo_summary_runs(self):
        result = self._run("--summary")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        for key in ("total_feedback", "helpful", "missed_or_corrected", "worst_memory_ids"):
            self.assertIn(key, data)

    def test_write_and_duplicate_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = f"""
import importlib.util, json, sys
from pathlib import Path
sys.path.insert(0, r"{SCRIPTS}")
spec = importlib.util.spec_from_file_location("rf", r"{SCRIPTS / 'record_feedback.py'}")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
tmp_path = Path(r"{tmp}") / "feedback.jsonl"
m.FEEDBACK = tmp_path
m.read_feedback = lambda path=tmp_path: [json.loads(line) for line in (tmp_path.read_text(encoding="utf-8").splitlines() if tmp_path.exists() else []) if line.strip()]
sys.argv = ["record_feedback.py", "--feedback-id", "feedback.test.001", "--memory-ids", "model.a,event.b", "--outcome", "corrected", "--note", "用户纠正了归属"]
try:
    m.main()
except SystemExit as exc:
    if exc.code:
        sys.exit(exc.code)
assert tmp_path.exists(), "first write should create feedback.jsonl"
row = m.read_feedback(tmp_path)[0]
assert row["outcome"] == "corrected" and row["memory_ids_used"] == ["model.a", "event.b"], row
sys.argv = ["record_feedback.py", "--feedback-id", "feedback.test.001", "--outcome", "helpful"]
try:
    m.main()
    sys.exit("duplicate write was not refused")
except SystemExit as exc:
    sys.exit(0)
"""
            result = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ColdRecallWindowTests(unittest.TestCase):
    def first_timeline_month(self):
        """Pick a month that actually has timeline entries; never assert on a personal date."""
        timeline_path = ROOT / "memory" / "v2" / "timeline.jsonl"
        if not timeline_path.is_file():
            self.skipTest("requires an initialized archive (memory/)")
        for line in timeline_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                month = str(json.loads(line).get("date_start", ""))[:7]
                if month:
                    return month
        self.skipTest("requires dated timeline entries")

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_window_returns_entries_without_keyword(self):
        month = self.first_timeline_month()
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "retrieve_v2.py"), "--window", month, "--level", "probe", "--no-trace"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["timeline"], f"the time window must contain entries (window: {month})")
        ids = {row.get("record_id") for row in data["timeline"]}
        self.assertTrue(any(isinstance(item, str) and item for item in ids))

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_window_range_filters_boundaries(self):
        month = self.first_timeline_month()
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "retrieve_v2.py"), "--window", f"{month}:{month}", "--level", "probe", "--no-trace"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["timeline"])
        self.assertTrue(all(str(row.get("date_start", "")).startswith(month) for row in data["timeline"]))


if __name__ == "__main__":
    unittest.main()
