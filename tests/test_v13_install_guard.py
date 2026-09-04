import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import install_mcp as im


class HijackGuardTests(unittest.TestCase):
    """§6.6: install_mcp must tell 'the skill really moved' from 'a copy/sandbox
    tree is hijacking the live registration' and refuse the latter. Never touches
    the user's real configs — all checks run against temp-dir config files."""

    def _json_cfg(self, root: Path, server_arg: str | None) -> Path:
        entry = {"command": "python", "args": [server_arg]} if server_arg else {"command": "python", "args": []}
        cfg = root / "config.json"
        cfg.write_text(json.dumps({"mcp": {"servers": {im.SERVER_NAME: entry}}}), encoding="utf-8")
        return cfg

    def test_still_existing_other_tree_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "live" / "scripts" / "mcp_server.py"
            old.parent.mkdir(parents=True); old.write_text("# old", encoding="utf-8")
            cfg = self._json_cfg(root, str(old))
            self.assertEqual(im.registered_server_path("zcode", cfg), str(old))
            self.assertTrue(im.hijack_block_reason(str(old)), "old tree still on disk must block")

    def test_gone_tree_self_heals(self):
        with tempfile.TemporaryDirectory() as tmp:
            gone = str(Path(tmp) / "moved-away" / "scripts" / "mcp_server.py")
            self.assertEqual(im.hijack_block_reason(gone), "", "a real move must still self-heal")

    def test_same_tree_and_unregistered_pass(self):
        self.assertEqual(im.hijack_block_reason(str(im.SERVER)), "", "same tree is a no-op, not a hijack")
        self.assertEqual(im.hijack_block_reason(None), "", "unregistered must be allowed")

    def test_codex_toml_path_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "live" / "scripts" / "mcp_server.py"
            old.parent.mkdir(parents=True); old.write_text("#x", encoding="utf-8")
            toml = root / "config.toml"
            toml.write_text(
                "[other]\nk=1\n\n[mcp_servers.personal-understanding]\ncommand = 'python'\n"
                f"args = ['{str(old)}']\n\n[mcp_servers.next]\n", encoding="utf-8")
            self.assertEqual(im.registered_server_path("codex", toml), str(old))

    def test_describe_entry_matches_quoted_arg(self):
        # a config that stored the arg with wrapping quotes must read as 'matches',
        # not falsely 'stale' (which would otherwise rewrite and trip the guard).
        self.assertEqual(im.describe_entry({"args": [f"'{im.SERVER}'"]}), "registered, path matches")
        self.assertEqual(im.describe_entry({"args": [str(im.SERVER)]}), "registered, path matches")


if __name__ == "__main__":
    unittest.main()
