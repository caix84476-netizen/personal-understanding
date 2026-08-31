import hashlib
import json
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from derivation_ledger import finalize_capture, link_record, load_ledger, register_capture
from turn_receipts import audit_turn, classify_personal_turn, create_receipt, mark_captured


def write_capture(root: Path, capture_id: str, text: str) -> None:
    folder = root / "sources" / "conversation"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{capture_id}.txt"
    path.write_text(text, encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps({
        "capture_id": capture_id,
        "captured_at": "2026-08-31T12:00:00+08:00",
        "source_path": path.relative_to(root).as_posix(),
        "utf8_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }), encoding="utf-8")


def register_in_other_process(root_text: str, capture_id: str) -> None:
    root = Path(root_text)
    register_capture(capture_id, source_path=f"sources/conversation/{capture_id}.txt", root=root)


class ReceiptAndConcurrencyTests(unittest.TestCase):
    def test_personal_material_in_a_rewrite_request_cannot_be_routed_away(self):
        text = "帮我顺一下这段：我玩到第一个故事时很恶心，也认真想了一会儿价值由谁定义。"
        decision = classify_personal_turn(text)
        self.assertTrue(decision["requires_personal_understanding"])
        self.assertIn("first-person-experience-or-state", decision["reasons"])
        self.assertFalse(classify_personal_turn("修复 Python 并发锁的 bug")["requires_personal_understanding"])

    def test_receipt_cannot_claim_completion_without_capture_and_closure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            text = "我最近因为一件事很焦虑。"
            receipt = create_receipt(text, turn_id="turn.test.receipt", root=root)
            self.assertEqual(audit_turn(receipt["turn_id"], root)["code"], "required-turn-not-captured")

            capture_id = "capture.test.receipt"
            write_capture(root, capture_id, text)
            register_capture(capture_id, source_path=f"sources/conversation/{capture_id}.txt", root=root)
            mark_captured(receipt["turn_id"], capture_id, root)
            self.assertEqual(audit_turn(receipt["turn_id"], root)["code"], "required-turn-not-closed")

            record = root / "memory" / "records" / "event.test.receipt.md"
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text("---\nid: event.test.receipt\nsource_refs: sources/conversation/capture.test.receipt.txt\n---\n", encoding="utf-8")
            link_record(capture_id, "event.test.receipt", root=root)
            finalize_capture(capture_id, "derived", root=root)
            self.assertTrue(audit_turn(receipt["turn_id"], root)["pass"])

    def test_two_processes_do_not_lose_ledger_updates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ids = ["capture.test.concurrent-a", "capture.test.concurrent-b"]
            for capture_id in ids:
                write_capture(root, capture_id, capture_id)
            processes = [multiprocessing.Process(target=register_in_other_process, args=(str(root), capture_id)) for capture_id in ids]
            for process in processes:
                process.start()
            for process in processes:
                process.join(15)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(set(load_ledger(root)), set(ids))


if __name__ == "__main__":
    unittest.main()
