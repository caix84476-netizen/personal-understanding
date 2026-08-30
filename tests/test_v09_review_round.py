"""Regression tests for the 2026-08-29 review round: salience placement,
shared due logic, corrupt-file tolerance, atomic writes, survey speed."""
import hashlib
import importlib.util
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

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def write_record(records: Path, record_id: str, kind: str = "event", last_confirmed: str = "2025-01-01", eol: str = "\n") -> Path:
    records.mkdir(parents=True, exist_ok=True)
    path = records / f"{record_id}.md"
    path.write_text(eol.join([
        "---",
        f"id: {record_id}",
        f"kind: {kind}",
        "status: current",
        "confidence: high",
        "sensitivity: ordinary",
        "source_refs: current-conversation",
        f"last_confirmed: {last_confirmed}",
        "---",
        "",
        "正文内容，不能被破坏。",
        "",
    ]), encoding="utf-8")
    return path


class SalienceApplyPlacementTests(unittest.TestCase):
    """apply_decay must write salience inside the frontmatter, not slice the body by line number."""

    def test_apply_keeps_frontmatter_intact_for_lf_and_crlf(self):
        sr = load_module("salience_review")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for eol, tag in (("\n", "lf"), ("\r\n", "crlf")):
                path = write_record(root / "memory" / "records", f"event.test.placement-{tag}", eol=eol)
                self.assertTrue(sr.apply_decay({"path": str(path)}, root=root))
                text = path.read_text(encoding="utf-8")
                fm = text.split("---")[1]
                self.assertIn(f"id: event.test.placement-{tag}", fm, f"{tag}: id was truncated")
                self.assertIn("salience: 0", fm, f"{tag}: salience is not inside the frontmatter")
                self.assertIn("salience_reviewed: ", fm)
                self.assertIn("正文内容，不能被破坏。", text)
                self.assertNotIn("salience: 0", text.split("---", 2)[2], f"{tag}: salience leaked into the body")

    def test_cli_apply_then_records_keep_valid_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SKILL.md").write_text("---\nname: personal-understanding\nversion: 2.1.0\n---\n\nbody\n", encoding="utf-8")
            (root / "VERSION").write_text("2.1.0", encoding="utf-8")
            path = write_record(root / "memory" / "records", "event.test.cli-apply")
            driver = f"""
import importlib.util, sys
from pathlib import Path
sys.path.insert(0, r"{SCRIPTS}")
import catalog_utils
catalog_utils.ROOT = Path(r"{root}")
spec = importlib.util.spec_from_file_location("sr", r"{SCRIPTS / 'salience_review.py'}")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sys.argv = ["salience_review.py", "--min-age-days", "0", "--apply"]
m.main()
sys.exit(0)
"""
            result = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = path.read_text(encoding="utf-8")
            fm = text.split("---")[1]
            self.assertIn("id: event.test.cli-apply", fm)
            self.assertIn("salience: 0", fm)


class SharedDueLogicTests(unittest.TestCase):
    def test_followup_is_due_truncates_time_and_matches_open_statuses(self):
        from v2_archive import followup_due_day, followup_is_due, followup_open
        row = {"id": "f", "status": "pending", "due_at": "2026-08-28T18:00:00"}
        self.assertTrue(followup_is_due(row, today="2026-08-29"))
        self.assertFalse(followup_is_due(row, today="2026-08-27"))
        self.assertEqual(followup_due_day(row), "2026-08-28")
        self.assertTrue(followup_open({"status": "overdue"}))
        self.assertFalse(followup_open({"status": "answered"}))

    def test_cli_followup_check_default_horizon_is_three_days(self):
        source = (SCRIPTS / "followup_check.py").read_text(encoding="utf-8")
        self.assertIn('"--horizon", type=int, default=3', source)


class CorruptFileToleranceTests(unittest.TestCase):
    def test_load_v2_and_audit_survive_corrupt_manifest(self):
        import v2_archive
        with tempfile.TemporaryDirectory() as tmp:
            original = v2_archive.V2_ROOT
            try:
                fake = Path(tmp) / "v2"
                fake.mkdir()
                (fake / "manifest.json").write_text("{ 损坏的 JSON", encoding="utf-8")
                (fake / "current-state.json").write_text("也不是 JSON", encoding="utf-8")
                v2_archive.V2_ROOT = fake
                data = v2_archive.load_v2()
                self.assertEqual(data["manifest"], {})
                audit = v2_archive.v2_audit()
                self.assertEqual(audit["status"], "failed")
                codes = {item.get("code") for item in audit["errors"]}
                self.assertIn("manifest-corrupt", codes)
            finally:
                v2_archive.V2_ROOT = original


class AtomicWriteTests(unittest.TestCase):
    def test_jsonl_write_leaves_no_tmp_file(self):
        from v2_archive import jsonl_write
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.jsonl"
            jsonl_write(path, [{"id": "b"}, {"id": "a"}])
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["id"] for row in rows], ["a", "b"])
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_session_check_reports_backup_and_feedback_reminders(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "session_check.py"), "--allow-warnings"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertIn(result.returncode, (0, 2), result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertIn("backup", data["maintenance_reminders"])
        self.assertIn("age_days", data["maintenance_reminders"]["backup"])
        self.assertIn("feedback", data["maintenance_reminders"])


class BackupMirrorConfigTests(unittest.TestCase):
    """USB mirror decision: with no USB drive it degrades to None; an explicit path always wins."""

    def test_mirror_target_falls_back_to_usb_and_none(self):
        import backup_archive
        self.assertIsNone(backup_archive.mirror_target("", {"usb_mirror": False, "mirror_to": ""}))
        drives = backup_archive.removable_drives()
        # On a machine without a USB drive, usb_mirror enabled must still return
        # None or a real removable drive — never a fixed drive.
        result = backup_archive.mirror_target("", {"usb_mirror": True, "mirror_to": "", "usb_volume_label": ""})
        if result is not None:
            self.assertIn(result, drives)
            self.assertNotEqual(result.drive, "C:\\")
        explicit = backup_archive.mirror_target("", {"usb_mirror": True, "mirror_to": "X:\\anywhere"})
        self.assertEqual(explicit, Path("X:\\anywhere"))

    def test_removable_drives_never_include_fixed_drive(self):
        import backup_archive
        for drive in backup_archive.removable_drives():
            self.assertNotEqual(str(drive).casefold(), "c:\\")


class MirrorBodyTests(unittest.TestCase):
    """Full-body mirror: incremental updates, no accumulating snapshots, stale files pruned."""

    def _make_source(self, src: Path) -> None:
        (src / "memory" / "records").mkdir(parents=True)
        (src / "memory" / "records" / "a.md").write_text("A", encoding="utf-8")
        (src / "SKILL.md").write_text("skill", encoding="utf-8")

    def test_mirror_is_incremental_and_prunes_stale(self):
        import backup_archive
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "skill"
            target = Path(tmp) / "usb"
            self._make_source(src)
            first = backup_archive.mirror_body(target, source_root=src)
            self.assertEqual(first["copied"], 2)
            dest = Path(first["target"])
            self.assertTrue((dest / "SKILL.md").exists())

            second = backup_archive.mirror_body(target, source_root=src)
            self.assertEqual(second["copied"], 0)
            self.assertEqual(second["unchanged"], 2)

            (src / "memory" / "records" / "a.md").write_text("A2", encoding="utf-8")
            (src / "SKILL.md").unlink()
            third = backup_archive.mirror_body(target, source_root=src)
            self.assertEqual(third["copied"], 1)
            self.assertEqual(third["removed_stale"], 1)
            self.assertFalse((dest / "SKILL.md").exists())
            self.assertEqual((dest / "memory" / "records" / "a.md").read_text(encoding="utf-8"), "A2")

class ZipPromotionTests(unittest.TestCase):
    """Zip refresh decision: once the window elapses, promote a new version (validation is a hard gate); skip when the body is unchanged."""

    def _state(self, promoted_days_ago: int | None, fingerprint: str = "fp1", today=None):
        from datetime import date as date_cls, timedelta
        today = today or date_cls(2026, 8, 29)
        state = {}
        if promoted_days_ago is not None:
            state["promoted_at"] = (today - timedelta(days=promoted_days_ago)).isoformat()
            state["body_fingerprint"] = "old-fingerprint"
        return state, today

    def test_should_promote_semantics(self):
        import backup_archive
        config = {"refresh_after_days": 7}
        with tempfile.TemporaryDirectory() as tmp:
            original = backup_archive.BACKUPS
            backup_archive.BACKUPS = Path(tmp)
            try:
                today = self._state(None)[1]
                # Never packaged yet: establish the baseline immediately
                due, reason = backup_archive.should_promote({}, "fp1", today, config)
                self.assertTrue(due)
                self.assertEqual(reason, "no-zip-yet")
                # Body unchanged since the last packaging: skip
                (backup_archive.stable_zip_path()).write_bytes(b"x")
                state = {"promoted_at": "2026-08-20", "body_fingerprint": "fp1"}
                due, reason = backup_archive.should_promote(state, "fp1", today, config)
                self.assertFalse(due)
                self.assertEqual(reason, "body-unchanged-zip-already-current")
                # One week elapsed: promote a new version
                state = {"promoted_at": "2026-08-20", "body_fingerprint": "old"}
                due, reason = backup_archive.should_promote(state, "fp-new", today, config)
                self.assertTrue(due)
                self.assertEqual(reason, "zip-9-days-old")
                # Window not elapsed yet: wait
                state = {"promoted_at": "2026-08-27", "body_fingerprint": "old"}
                due, reason = backup_archive.should_promote(state, "fp-new", today, config)
                self.assertFalse(due)
                self.assertEqual(reason, "waiting-refresh-window")
            finally:
                backup_archive.BACKUPS = original

    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_promotion_keeps_previous_generation(self):
        import backup_archive
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "skill"
            backups = Path(tmp) / "backups"
            (src / "memory").mkdir(parents=True)
            (src / "SKILL.md").write_text("v1", encoding="utf-8")
            first = backup_archive.promote_stable(source_root=src, backups_dir=backups)
            self.assertTrue(first["promoted"])
            self.assertFalse(first["previous_kept"])
            self.assertEqual((backups / backup_archive.STABLE_ZIP).read_bytes(), (backups / backup_archive.STABLE_ZIP).read_bytes())
            (src / "SKILL.md").write_text("v2", encoding="utf-8")
            second = backup_archive.promote_stable(source_root=src, backups_dir=backups)
            self.assertTrue(second["promoted"])
            self.assertTrue(second["previous_kept"])
            # previous = the last generation (v1); stable = the current one (v2)
            with __import__("zipfile").ZipFile(backups / backup_archive.PREVIOUS_ZIP) as zf:
                self.assertEqual(zf.read("SKILL.md"), b"v1")
            with __import__("zipfile").ZipFile(backups / backup_archive.STABLE_ZIP) as zf:
                self.assertEqual(zf.read("SKILL.md"), b"v2")
            # backups are capped: only the fixed files, never growing with runs
            names = {p.name for p in backups.glob("*.zip")}
            self.assertEqual(names, {backup_archive.STABLE_ZIP, backup_archive.PREVIOUS_ZIP})


class InstallerExportTests(unittest.TestCase):
    def test_export_writes_parseable_universal_snippets(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "install_mcp.py"), "--export-dir", tmp],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            block = json.loads((Path(tmp) / "mcpServers.json").read_text(encoding="utf-8"))
            entry = block["mcpServers"]["personal-understanding"]
            self.assertIn("mcp_server.py", entry["args"][0])
            self.assertEqual(entry["env"]["PYTHONUTF8"], "1")
            guide = (Path(tmp) / "HOW-TO-ADD.md").read_text(encoding="utf-8")
            self.assertIn("mcpServers", guide)
            self.assertIn("[mcp_servers.personal-understanding]", guide)


class SurveyFastPathTests(unittest.TestCase):
    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
    def test_survey_uses_light_header_and_keeps_contract(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "catalog_context.py"), "--view", "survey"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertIn("policy", data)
        self.assertIn("decision_contract", data)
        self.assertGreaterEqual(data["survey_counts"]["current"], 100)
        # The spine is bucketed by phase: several phases must appear, not just the most recent entries
        phases = {row.get("phase") for row in data["v2"]["spine"]}
        self.assertGreater(len(phases), 3, f"spine should cover several phases: {phases}")

    def test_retrieve_v2_persists_trace_and_fidelity_chips(self):
        # retrieve_v2 persists a decision trace, so run it against a temp copy
        # with a synthetic archive instead of the real repository.
        with tempfile.TemporaryDirectory() as tmp:
            repo = _fixture.make_temp_repo(Path(tmp))
            v2 = repo / "memory" / "v2"
            verbatim = "High school football final"
            (v2 / "timeline.jsonl").write_text(json.dumps({
                "id": "event.test.demo-football",
                "record_id": "event.test.demo-football",
                "title": "High school football final",
                "summary": "A synthetic fixture event about a high school football match.",
                "date_start": "2026-05-01",
                "status": "current",
                "salience": 3,
                "fragment_refs": ["fragment.capture.test-demo"],
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            (v2 / "fragments.jsonl").write_text(json.dumps({
                "id": "fragment.capture.test-demo",
                "fidelity": "verbatim",
                "verbatim": verbatim,
                "verbatim_sha256": hashlib.sha256(verbatim.encode("utf-8")).hexdigest(),
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(repo / "scripts" / "retrieve_v2.py"), "--query", "high school football", "--level", "probe"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data["timeline"])
            self.assertTrue(all("evidence_fidelity" in row for row in data["timeline"]))
            self.assertIsNotNone(data.get("trace_path"))
            trace_file = repo / data["trace_path"]
            self.assertTrue(trace_file.exists())
            rows = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any(row.get("query") == "high school football" for row in rows))


if __name__ == "__main__":
    unittest.main()
