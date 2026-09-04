"""Tests for restore_stable.py — evaluation-policy item 13 (migration rollback)."""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_module(root: Path):
    spec = importlib.util.spec_from_file_location("restore_stable_test", SCRIPTS / "restore_stable.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    module.BACKUPS = root / "backups"
    module.STABLE_ZIP = module.BACKUPS / "personal-understanding-stable.zip"
    module.STABLE_MANIFEST = module.BACKUPS / "personal-understanding-stable.json"
    return module


def make_backup(root: Path, files: dict[str, str]) -> None:
    backups = root / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    zip_path = backups / "personal-understanding-stable.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    manifest = backups / "personal-understanding-stable.json"
    manifest.write_text(json.dumps({"sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest()}), encoding="utf-8")


class RestoreStableTests(unittest.TestCase):
    def test_verify_zip_accepts_matching_hash_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_backup(root, {"scripts/foo.py": "print(1)"})
            module = load_module(root)
            module.verify_zip()  # must not exit
            (root / "backups" / "personal-understanding-stable.zip").write_bytes(b"tampered")
            with self.assertRaises(SystemExit):
                module.verify_zip()

    def test_scope_filters_code_vs_data_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_backup(root, {"scripts/foo.py": "x", "SKILL.md": "s", "memory/records/a.md": "y", "sources/conversation/z.txt": "w"})
            module = load_module(root)
            code = set(module.scope_members("code"))
            data = set(module.scope_members("data"))
            allm = set(module.scope_members("all"))
            self.assertEqual(code, {"scripts/foo.py", "SKILL.md"})
            self.assertEqual(data, {"memory/records/a.md", "sources/conversation/z.txt"})
            self.assertEqual(allm, code | data)

    def test_apply_restores_files_and_snapshots_preexisting_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_backup(root, {"scripts/foo.py": "restored content"})
            existing = root / "scripts" / "foo.py"
            existing.parent.mkdir(parents=True)
            existing.write_text("CORRUPTED", encoding="utf-8")
            module = load_module(root)
            module.apply(module.scope_members("code"))
            self.assertEqual(existing.read_text(encoding="utf-8"), "restored content")
            snaps = list((root / "backups").glob("pre-restore-*"))
            self.assertEqual(len(snaps), 1, "a pre-restore snapshot dir must exist")
            self.assertEqual((snaps[0] / "scripts" / "foo.py").read_text(encoding="utf-8"), "CORRUPTED")

    def test_dry_run_plan_does_not_touch_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_backup(root, {"scripts/foo.py": "new"})
            existing = root / "scripts" / "foo.py"
            existing.parent.mkdir(parents=True)
            existing.write_text("keep me", encoding="utf-8")
            module = load_module(root)
            overwrite, add, local_only = module.plan(module.scope_members("code"))
            self.assertEqual(overwrite, ["scripts/foo.py"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep me")  # plan writes nothing


if __name__ == "__main__":
    unittest.main()
