import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fixture

from cli_runtime import CliReadGateError, declare_maintenance_read, require_cli_capture

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


class CliCaptureGateTests(unittest.TestCase):
    """§6.5: the CLI read gate mirrors the MCP capture-before-read discipline,
    with a maintenance escape valve so internal tools/CI keep working."""

    def _seed_capture(self, root: Path, capture_id: str) -> None:
        folder = root / "sources" / "conversation"
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / f"{capture_id}.txt"
        source.write_text("原话", encoding="utf-8")
        (folder / f"{capture_id}.json").write_text(json.dumps({
            "capture_id": capture_id, "captured_at": "2026-09-04T12:00:00+08:00",
            "message_kind": "user-message", "source_path": source.relative_to(root).as_posix(),
            "utf8_sha256": "test"}), encoding="utf-8")

    def test_maintenance_key_skips_the_gate(self):
        self.assertEqual(require_cli_capture("", maintenance=True, root=ROOT), "maintenance")

    def test_bare_read_is_refused(self):
        with self.assertRaises(CliReadGateError):
            require_cli_capture("", maintenance=False, root=ROOT)

    def test_bogus_capture_is_refused_but_real_capture_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_capture(root, "cap.turn.real")
            with self.assertRaises(CliReadGateError):
                require_cli_capture("cap.does.not.exist", maintenance=False, root=root)
            self.assertEqual(require_cli_capture("cap.turn.real", maintenance=False, root=root), "captured")

    def test_declare_maintenance_injects_key_after_script_name(self):
        argv = ["--query", "test"]
        self.assertEqual(declare_maintenance_read([str(SCRIPTS / "retrieve_v2.py")] + argv)[:2],
                         [str(SCRIPTS / "retrieve_v2.py"), "--maintenance"])
        self.assertIn("--maintenance", declare_maintenance_read([str(SCRIPTS / "catalog_context.py"), "--view", "survey"]))

    def test_cli_subprocess_gate_exit_codes(self):
        # bare read → rc 2 with a refusal; maintenance → rc 0. Exercises the real
        # argparse wiring, not just the helper.
        bare = subprocess.run([sys.executable, str(SCRIPTS / "retrieve_v2.py"), "--query", "妈 转钱", "--no-trace"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(bare.returncode, 2, bare.stdout)
        self.assertIn("拒绝读取", bare.stderr)
        ok = subprocess.run([sys.executable, str(SCRIPTS / "retrieve_v2.py"), "--maintenance", "--query", "妈 转钱", "--no-trace", "--format", "json"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("retrieval_version", ok.stdout)

    def test_survey_write_does_not_crash_on_light_header(self):
        # latent 2.4.0 bug: --view survey --write built the light header (no `records`
        # key) then write_catalog KeyError'd. --write must build the full catalog.
        root = _fixture.make_temp_repo(Path(tempfile.mkdtemp(prefix="pu-write-")))
        (root / "memory" / "records" / "event.demo.md").write_text(
            "\n".join(["---", "id: event.demo", "kind: event", "status: current", "confidence: high",
                        "sensitivity: ordinary", "domain: domain.demo", "---", "", "内容", ""]),
            encoding="utf-8")
        result = subprocess.run([sys.executable, str(root / "scripts" / "catalog_context.py"),
                                 "--view", "survey", "--write", "--maintenance", "--format", "json"],
                                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        self.assertTrue((root / "memory" / "catalog.json").is_file())


if __name__ == "__main__":
    unittest.main()
