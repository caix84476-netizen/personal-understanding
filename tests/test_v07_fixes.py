"""Regression tests for the 2026-08-28 usability fix round."""
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
sys.path.insert(0, str(SCRIPTS))

from v2_archive import parse_open_loops


def run_driver(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


class SupersedeRegexTests(unittest.TestCase):
    def test_update_state_supersedes_old_current_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / "memory" / "records"
            records.mkdir(parents=True)
            old = records / "state.test.old.md"
            old.write_text(
                "\n".join([
                    "---",
                    "id: state.test.old",
                    "kind: state",
                    "status: current",
                    "confidence: high",
                    "sensitivity: ordinary",
                    "source_refs: current-conversation",
                    "---",
                    "",
                    "旧状态正文",
                    "",
                ]),
                encoding="utf-8",
            )
            source_dir = root / "sources" / "conversation"
            source_dir.mkdir(parents=True)
            (source_dir / "x.txt").write_text("来源原话", encoding="utf-8")
            driver = f"""
import importlib.util, sys
from pathlib import Path
sys.path.insert(0, r"{SCRIPTS}")
import catalog_utils
catalog_utils.ROOT = Path(r"{root}")
catalog_utils.RECORDS = Path(r"{root}") / "memory" / "records"
catalog_utils.SOURCES = Path(r"{root}") / "sources"
spec = importlib.util.spec_from_file_location("us", r"{SCRIPTS / 'update_state.py'}")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.ROOT = Path(r"{root}")
sys.argv = ["update_state.py", "--id", "state.test.old", "--content", "新状态", "--source", "sources/conversation/x.txt", "--apply"]
try:
    m.main()
except SystemExit as exc:
    sys.exit(exc.code if isinstance(exc.code, int) else 0)
sys.exit(0)
"""
            result = run_driver(driver)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("status: superseded", old.read_text(encoding="utf-8"))
            new_files = list(records.glob("state.test.old.*.md"))
            self.assertEqual(len(new_files), 1)
            self.assertIn("新状态", new_files[0].read_text(encoding="utf-8"))


class OpenLoopsParsingTests(unittest.TestCase):
    def test_legend_and_closed_loops_are_not_imported_as_followups(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "open-loops.md"
            path.write_text(
                "\n".join([
                    "# Open Loops",
                    "",
                    "## Pending",
                    "",
                    "- id: loop.a.20260101",
                    "  status: answered",
                    "  question: 已回答的问题",
                    "  closed_on: 2026-01-02",
                    "",
                    "- id: loop.b.20260103",
                    "  status: pending",
                    "  question: 真正待回访的问题",
                    "  asked_on: 2026-01-03",
                    "",
                    "## Lifecycle",
                    "",
                    "- `pending`: must be surfaced when relevant.",
                    "- `deferred`: the user asked to postpone it.",
                    "",
                ]),
                encoding="utf-8",
            )
            entries = parse_open_loops(path)
            ids = [entry.get("id") for entry in entries]
            self.assertIn("loop.a.20260101", ids)
            self.assertIn("loop.b.20260103", ids)
            self.assertEqual(len(entries), 2)


class FollowupHorizonTests(unittest.TestCase):
    def test_upcoming_uses_default_horizon_and_due_filters_by_date(self):
        import v2_archive
        from followup_check import check_followups
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "followups.jsonl"
            tmp_path.write_text(
                "\n".join([
                    json.dumps({"id": "f.due", "prompt": "到期", "context": "到期", "status": "pending", "due_at": "2026-08-27"}, ensure_ascii=False),
                    json.dumps({"id": "f.tomorrow", "prompt": "明天到期", "context": "明天", "status": "pending", "due_at": "2026-08-29"}, ensure_ascii=False),
                    json.dumps({"id": "f.future", "prompt": "远期", "context": "远期", "status": "pending", "due_at": "2099-06-01"}, ensure_ascii=False),
                ]) + "\n",
                encoding="utf-8",
            )
            original = v2_archive.JSONL_FILES["followups"]
            v2_archive.JSONL_FILES["followups"] = tmp_path
            try:
                result = check_followups(as_of="2026-08-28")
            finally:
                v2_archive.JSONL_FILES["followups"] = original
            self.assertEqual([row["id"] for row in result["due"]], ["f.due"])
            self.assertEqual([row["id"] for row in result["upcoming"]], ["f.tomorrow"])
            self.assertEqual(result["undated_pending"], [])


class StalePageCleanupTests(unittest.TestCase):
    def test_rebuild_removes_stale_v2_pages(self):
        # Rebuild writes derived views, so run it inside a temp copy of the skill tree.
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fixture.make_temp_repo(Path(tmp))
            stale = repo / "memory" / "v2" / "pages" / "entities" / "entity.stale.ghost-page.md"
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text("# Ghost page\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(repo / "scripts" / "rebuild_views.py")],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(stale.exists(), "stale entity pages must be removed on rebuild")


class StdinCaptureTests(unittest.TestCase):
    def test_capture_user_update_accepts_stdin_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = f"""
import importlib.util, io, sys
from pathlib import Path
sys.path.insert(0, r"{SCRIPTS}")
spec = importlib.util.spec_from_file_location("cu", r"{SCRIPTS / 'capture_user_update.py'}")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.CAPTURES = Path(r"{tmp}")
m.ROOT = Path(r"{tmp}")
m.register_capture = lambda *a, **k: None
m.read_receipt = lambda *a, **k: {{
    "requires_personal_understanding": True,
    "message_sha256": __import__("hashlib").sha256(
        "这是一段通过 stdin 传入的原话".encode("utf-8")
    ).hexdigest(),
}}
m.mark_captured = lambda *a, **k: None

class FakeProc:
    returncode = 2
    stdout = ""
    stderr = ""

m.subprocess.run = lambda *a, **k: FakeProc()
payload = "这是一段通过 stdin 传入的原话".encode("utf-8")
sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
sys.argv = ["capture_user_update.py", "--stdin", "--capture-id", "capture.test.stdin-roundtrip", "--turn-id", "turn.test.stdin-roundtrip"]
try:
    m.main()
except SystemExit as exc:
    sys.exit(exc.code if isinstance(exc.code, int) else 0)
sys.exit(0)
"""
            result = run_driver(driver)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            written = Path(tmp) / "capture.test.stdin-roundtrip.txt"
            self.assertEqual(written.read_text(encoding="utf-8"), "这是一段通过 stdin 传入的原话")


if __name__ == "__main__":
    unittest.main()
