import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from turn_receipts import audit_turn, classify_personal_turn, create_receipt, mark_captured, mark_closed_for_capture


class ThreeTierClassificationTests(unittest.TestCase):
    def test_auto_is_pure_content_classification(self):
        self.assertFalse(classify_personal_turn("《只狼》怎么打弦一郎？卡一下午了")["requires_personal_understanding"])
        self.assertTrue(classify_personal_turn("我今天感觉很难过")["requires_personal_understanding"])
        decision = classify_personal_turn("修复 Python 并发锁的 bug")
        self.assertFalse(decision["requires_personal_understanding"])
        self.assertEqual(decision["signal"], "technical")

    def test_light_declares_footprint_even_without_content_keywords(self):
        decision = classify_personal_turn("《只狼》怎么打弦一郎？", tier="light")
        self.assertTrue(decision["requires_personal_understanding"])
        self.assertEqual(decision["signal"], "personal-light")
        self.assertIn("model-declared-light-tier", decision["reasons"])
        self.assertEqual(decision["reasons_suppressed"], [])

    def test_full_is_the_fallback_declaration(self):
        decision = classify_personal_turn("随便聊聊", tier="full")
        self.assertTrue(decision["requires_personal_understanding"])
        self.assertEqual(decision["signal"], "personal")

    def test_skip_forces_not_required_but_keeps_suppressed_trail(self):
        decision = classify_personal_turn("我今天感觉很难过", tier="skip")
        self.assertFalse(decision["requires_personal_understanding"])
        self.assertEqual(decision["reasons"], ["no-personal-material-detected"])
        self.assertIn("first-person-experience-or-state", decision["reasons_suppressed"])

    def test_invalid_tier_is_rejected(self):
        with self.assertRaises(ValueError):
            classify_personal_turn("x", tier="Light")
        with self.assertRaises(ValueError):
            classify_personal_turn("x", tier="sometimes")

    def test_receipt_schema_carries_tier(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = create_receipt("今天吃什么", turn_id="turn.tier.skip", tier="skip", root=root)
            self.assertEqual(receipt["schema_version"], "1.1.1")
            self.assertEqual(receipt["tier"], "skip")
            self.assertFalse(receipt["requires_personal_understanding"])


class LightClosureGateTests(unittest.TestCase):
    def _light_receipt_with_capture(self, root: Path, turn_id: str, capture_id: str) -> None:
        create_receipt("宿舍四人间怎么摆好看", turn_id=turn_id, tier="light", root=root)
        mark_captured(turn_id, capture_id, root=root)

    def test_light_turn_closed_without_derivation_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._light_receipt_with_capture(root, "turn.light.gate1", "cap.light.gate1")
            mark_closed_for_capture("cap.light.gate1", "no-derivation-needed", root=root)
            verdict = audit_turn("turn.light.gate1", root)
            self.assertFalse(verdict["pass"])
            self.assertEqual(verdict["code"], "light-tier-requires-derived-record")

    def test_light_turn_closed_with_derivation_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._light_receipt_with_capture(root, "turn.light.gate2", "cap.light.gate2")
            mark_closed_for_capture("cap.light.gate2", "derived", root=root)
            self.assertTrue(audit_turn("turn.light.gate2", root)["pass"])

    def test_full_turn_may_still_close_without_derivation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_receipt("有点迷茫", turn_id="turn.full.gate", tier="full", root=root)
            mark_captured("turn.full.gate", "cap.full.gate", root=root)
            mark_closed_for_capture("cap.full.gate", "no-derivation-needed", root=root)
            self.assertTrue(audit_turn("turn.full.gate", root)["pass"])

    def test_skip_receipt_passes_audit_without_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_receipt("帮我看看买哪个手机", turn_id="turn.skip.gate", tier="skip", root=root)
            self.assertTrue(audit_turn("turn.skip.gate", root)["pass"])


if __name__ == "__main__":
    unittest.main()
