import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from derivation_ledger import (
    audit_ledger,
    bootstrap_ledger,
    finalize_capture,
    link_record,
    load_ledger,
    register_capture,
)
from v2_archive import capture_fragment_parity_errors, capture_records, infer_entity_type


def write_capture(root: Path, capture_id: str, text: str = "原话") -> None:
    folder = root / "sources" / "conversation"
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / f"{capture_id}.txt"
    source.write_text(text, encoding="utf-8")
    meta = {
        "capture_id": capture_id,
        "captured_at": "2026-08-26T12:00:00+08:00",
        "message_kind": "user-message",
        "source_path": source.relative_to(root).as_posix(),
        "utf8_sha256": "test",
    }
    source.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")


def write_record(root: Path, record_id: str, capture_id: str) -> None:
    folder = root / "memory" / "records"
    folder.mkdir(parents=True, exist_ok=True)
    source = f"sources/conversation/{capture_id}.txt"
    (folder / f"{record_id}.md").write_text(
        "\n".join([
            "---",
            f"id: {record_id}",
            "kind: event",
            "status: current",
            "confidence: high",
            "sensitivity: private",
            f"source_refs: {source}",
            f"verbatim_refs: fragment.capture.{capture_id}",
            "---",
            "",
            "Derived record.",
            "",
        ]),
        encoding="utf-8",
    )


class DerivationClosureTests(unittest.TestCase):
    def test_capture_registration_is_pending_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_capture(root, "capture.test.pending")
            register_capture("capture.test.pending", source_path="sources/conversation/capture.test.pending.txt", root=root)
            self.assertEqual(load_ledger(root)["capture.test.pending"]["status"], "pending")
            audit = audit_ledger(root)
            self.assertIn("capture.test.pending", audit["pending_capture_ids"])
            self.assertTrue(any(item["code"] == "capture-pending-derivation" for item in audit["warnings"]))

    def test_derived_requires_a_linked_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_capture(root, "capture.test.no-record")
            register_capture("capture.test.no-record", source_path="sources/conversation/capture.test.no-record.txt", root=root)
            with self.assertRaises(ValueError):
                finalize_capture("capture.test.no-record", "derived", root=root)

    def test_link_then_finalize_derived(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_capture(root, "capture.test.linked")
            write_record(root, "event.test.linked", "capture.test.linked")
            register_capture("capture.test.linked", source_path="sources/conversation/capture.test.linked.txt", root=root)
            link_record("capture.test.linked", "event.test.linked", root=root)
            entry = finalize_capture("capture.test.linked", "derived", root=root)
            self.assertEqual(entry["status"], "derived")
            self.assertEqual(entry["record_ids"], ["event.test.linked"])
            self.assertEqual(audit_ledger(root)["status"], "clean")

    def test_no_derivation_needed_requires_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_capture(root, "capture.test.duplicate")
            register_capture("capture.test.duplicate", source_path="sources/conversation/capture.test.duplicate.txt", root=root)
            with self.assertRaises(ValueError):
                finalize_capture("capture.test.duplicate", "no-derivation-needed", root=root)
            entry = finalize_capture("capture.test.duplicate", "no-derivation-needed", "exact SHA-256 duplicate; a complete derivation already exists", root=root)
            self.assertEqual(entry["status"], "no-derivation-needed")

    def test_bootstrap_discovers_and_links_existing_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_capture(root, "capture.test.bootstrap")
            write_record(root, "event.test.bootstrap", "capture.test.bootstrap")
            result = bootstrap_ledger(root)
            self.assertEqual(result["created"], 1)
            self.assertEqual(load_ledger(root)["capture.test.bootstrap"]["status"], "derived")

    def test_capture_output_does_not_claim_derived(self):
        source = (SCRIPTS / "capture_user_update.py").read_text(encoding="utf-8")
        self.assertIn('"derivation_status": "pending"', source)
        self.assertNotIn('"derived":', source)

    def test_validator_has_closed_capture_gate(self):
        source = (SCRIPTS / "validate_memory.py").read_text(encoding="utf-8")
        self.assertIn("--require-closed-captures", source)
        self.assertIn("capture-pending-derivation", source)
        self.assertIn("capture-untracked", source)

    def test_mcp_exposes_closure_tools_and_attachment_capture_support(self):
        payload = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n'
        result = subprocess.run([sys.executable, str(SCRIPTS / "mcp_server.py")], input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        names = {tool["name"] for tool in data["result"]["tools"]}
        self.assertTrue({"personal_finalize_capture", "personal_derivation_status"}.issubset(names))
        source = (SCRIPTS / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn("discover_captures(ROOT).get(capture_id)", source)

    def test_mcp_post_write_validation_requires_closed_captures(self):
        spec = importlib.util.spec_from_file_location("mcp_server_closure_test", SCRIPTS / "mcp_server.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)

        calls = []

        def fake_run_script(name, args):
            calls.append((name, args))
            return 0, name

        with patch.object(module, "run_script", side_effect=fake_run_script):
            module.rebuild_and_validate()
            result = module.handle("tools/call", {"name": "personal_validate", "arguments": {}})

        self.assertIn(("validate_memory.py", ["--require-closed-captures"]), calls)
        self.assertIn(("validate_memory.py", ["--json", "--require-closed-captures"]), calls)
        self.assertFalse(result["isError"])

    def test_mcp_validate_keeps_strict_option_with_closed_capture_gate(self):
        spec = importlib.util.spec_from_file_location("mcp_server_strict_closure_test", SCRIPTS / "mcp_server.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)

        with patch.object(module, "run_script", return_value=(0, "ok")) as run_script:
            module.handle("tools/call", {"name": "personal_validate", "arguments": {"strict": True}})

        run_script.assert_called_once_with("validate_memory.py", ["--json", "--require-closed-captures", "--strict"])

    def test_attachment_exact_duplicate_is_reused(self):
        spec = importlib.util.spec_from_file_location("capture_attachment_test", SCRIPTS / "capture_attachment.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = root / "sources" / "images"
            attachments = root / "sources" / "attachments"
            images.mkdir(parents=True)
            attachments.mkdir(parents=True)
            original = images / "existing.jpg"
            incoming = root / "incoming.jpg"
            original.write_bytes(b"same-binary")
            incoming.write_bytes(b"same-binary")
            old_root, old_attachments = module.ROOT, module.ATTACHMENTS
            try:
                module.ROOT = root
                module.ATTACHMENTS = attachments
                duplicate = module.find_duplicate(incoming, module.sha256_file(incoming))
            finally:
                module.ROOT, module.ATTACHMENTS = old_root, old_attachments
            self.assertEqual(duplicate, original)


    def test_capture_fragment_parity_uses_independent_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_capture(root, "capture.test.parity")
            missing = capture_fragment_parity_errors([], root)
            self.assertEqual(missing, [{"code": "capture-fragment-missing", "capture_id": "capture.test.parity"}])
            self.assertEqual(capture_fragment_parity_errors(["fragment.capture.capture.test.parity"], root), [])

    def test_image_metadata_capture_is_discovered_by_v2(self):
        import v2_archive
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = root / "sources" / "images"
            conversation = root / "sources" / "conversation"
            images.mkdir(parents=True)
            conversation.mkdir(parents=True)
            image = images / "capture.test.image.jpg"
            image.write_bytes(b"image-binary")
            (images / "capture.test.image.json").write_text(json.dumps({
                "capture_id": "capture.test.image",
                "captured_at": "2026-08-26T12:00:00+08:00",
                "speaker": "user",
                "message_kind": "image-attachment",
                "source_path": "sources/images/capture.test.image.jpg",
                "sha256": "abc123",
                "byte_length": 12,
            }), encoding="utf-8")
            old_root, old_conversation, old_images = v2_archive.ROOT, v2_archive.CONVERSATION_ROOT, v2_archive.IMAGES_ROOT
            try:
                v2_archive.ROOT = root
                v2_archive.CONVERSATION_ROOT = conversation
                v2_archive.IMAGES_ROOT = images
                captures = capture_records()
            finally:
                v2_archive.ROOT, v2_archive.CONVERSATION_ROOT, v2_archive.IMAGES_ROOT = old_root, old_conversation, old_images
            capture = next(item for item in captures if item["capture_id"] == "capture.test.image")
            self.assertEqual(capture["capture_kind"], "attachment")
            self.assertEqual(capture["content_type"], "image/jpeg")

    def test_place_prefix_stays_place(self):
        self.assertEqual(infer_entity_type("entity.place.example-lake", "lake"), "place")


if __name__ == "__main__":
    unittest.main()
