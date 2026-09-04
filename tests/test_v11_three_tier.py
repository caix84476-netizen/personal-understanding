import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from turn_receipts import audit_turn, classify_personal_turn, create_receipt, mark_captured, mark_closed_for_capture


class TwoTierClassificationTests(unittest.TestCase):
    def test_auto_is_pure_content_classification(self):
        self.assertFalse(classify_personal_turn("《只狼》怎么打弦一郎？卡一下午了")["requires_personal_understanding"])
        self.assertTrue(classify_personal_turn("我今天感觉很难过")["requires_personal_understanding"])
        decision = classify_personal_turn("修复 Python 并发锁的 bug")
        self.assertFalse(decision["requires_personal_understanding"])
        self.assertEqual(decision["signal"], "technical")

    def test_strong_affect_words_fire_without_subject(self):
        # §8: Chinese drops the subject; 抒发/状态 turns must recall without 我.
        for msg in ("有点烦，不知道干嘛", "挺焦虑的", "下巴冒痘了挺烦", "今天心情很差", "被说了一顿有点委屈"):
            decision = classify_personal_turn(msg)
            self.assertTrue(decision["requires_personal_understanding"], msg)
            self.assertIn("affective-or-state-without-subject", decision["reasons"], msg)

    def test_technical_context_vetoes_strong_word(self):
        # A strong affect word inside a technical turn must stay technical —
        # the churn the user would feel if every bug-complaint opened a capture.
        self.assertFalse(classify_personal_turn("这个 bug 的报错太烦了")["requires_personal_understanding"])
        self.assertFalse(classify_personal_turn("这配置烦死了改不动")["requires_personal_understanding"])

    def test_light_tier_is_normalized_to_full(self):
        # 2.4.0 两档制：轻量档并入完整档。tier=light 枚举仅为兼容保留，
        # 声明一律按 full 处理；活动足迹轮次改受 SKILL.md 足迹纪律约束，不再是独立档位。
        decision = classify_personal_turn("《只狼》怎么打弦一郎？", tier="light")
        self.assertTrue(decision["requires_personal_understanding"])
        self.assertEqual(decision["tier"], "full")
        self.assertEqual(decision["signal"], "personal")
        self.assertEqual(decision["reasons_suppressed"], [])

    def test_full_is_the_fallback_declaration(self):
        decision = classify_personal_turn("随便聊聊", tier="full")
        self.assertTrue(decision["requires_personal_understanding"])
        self.assertEqual(decision["signal"], "personal")

    def test_tier_upgrade_takes_effect_on_same_turn_id(self):
        # §8.1: re-declaring full after an auto miss must NOT be silently dropped.
        # A model that instead invents a new turn id leaks duplicate receipts, so
        # the upgrade rewrites the decision under the same turn_id.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            msg = "兵役登记搞完表打印交武装部"
            first = create_receipt(msg, turn_id="turn.upgrade", tier="auto", root=root)
            self.assertFalse(first["requires_personal_understanding"])
            second = create_receipt(msg, turn_id="turn.upgrade", tier="full", root=root)
            self.assertTrue(second["requires_personal_understanding"])
            self.assertEqual(second["turn_id"], "turn.upgrade")  # reused, not a new receipt
            self.assertEqual(second.get("tier_upgraded_from"), "auto")
            self.assertEqual(second["capture_status"], "required")
            # only one receipt file exists for this turn
            self.assertEqual(list((root / "memory" / "turn-receipts").glob("*.json")).__len__(), 1)

    def test_tier_downgrade_is_refused(self):
        # Suppressing already-required personal material with skip is the guardrail
        # violation the receipt trail exists to catch; re-declaring skip after full
        # must raise rather than quietly un-require the turn.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_receipt("我今天感觉很难过", turn_id="turn.downgrade", tier="full", root=root)
            with self.assertRaises(ValueError):
                create_receipt("我今天感觉很难过", turn_id="turn.downgrade", tier="skip", root=root)

    def test_same_outcome_redeclare_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_receipt("随便聊聊", turn_id="turn.idem", tier="full", root=root)
            again = create_receipt("随便聊聊", turn_id="turn.idem", tier="full", root=root)
            self.assertTrue(again["requires_personal_understanding"])
            self.assertNotIn("tier_upgraded_at", again)  # no churn when the outcome is unchanged

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


class FootprintClosureTests(unittest.TestCase):
    def _footprint_receipt_with_capture(self, root: Path, turn_id: str, capture_id: str) -> None:
        create_receipt("宿舍四人间怎么摆好看", turn_id=turn_id, tier="light", root=root)
        mark_captured(turn_id, capture_id, root=root)

    def test_footprint_turn_may_close_with_no_derivation(self):
        # 两档制：足迹纪律允许查重零新增时以 no-derivation-needed 收场，
        # 旧的 light-tier-requires-derived-record 门禁已随三档制一并移除。
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._footprint_receipt_with_capture(root, "turn.light.gate1", "cap.light.gate1")
            mark_closed_for_capture("cap.light.gate1", "no-derivation-needed", root=root)
            verdict = audit_turn("turn.light.gate1", root)
            self.assertTrue(verdict["pass"])
            self.assertEqual(verdict["receipt"]["tier"], "full")

    def test_footprint_turn_closed_with_derivation_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._footprint_receipt_with_capture(root, "turn.light.gate2", "cap.light.gate2")
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

    def test_preflight_personal_turn_carries_low_signal_snapshot(self):
        # §8: the low-signal fast path is documented as reading "due follow-ups +
        # current-state snapshot" from preflight output. A personal-required turn
        # must literally carry that snapshot; a skip/non-personal turn stays lean.
        sys.path.insert(0, str(ROOT / "tests"))
        from _fixture import make_temp_repo
        root = make_temp_repo(Path(tempfile.mkdtemp(prefix="pu-preflight-")))
        proc = subprocess.run(
            [sys.executable, str(root / "scripts" / "preflight_context.py"), "最近有点烦", "--tier", "full",
             "--turn-id", "turn.snap.personal", "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        data = json.loads(proc.stdout)
        self.assertIn("current_state_snapshot", data)
        self.assertTrue(data["current_state_snapshot"]["available"])
        self.assertIn("followups", data)
        # skip-tier turn does not pay for the snapshot
        proc2 = subprocess.run(
            [sys.executable, str(root / "scripts" / "preflight_context.py"), "帮我看看买哪个手机", "--tier", "skip",
             "--turn-id", "turn.snap.skip", "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        data2 = json.loads(proc2.stdout)
        self.assertFalse(data2["current_state_snapshot"]["available"])


class MultiCaptureFinalizeSemanticsTests(unittest.TestCase):
    """正文+附件的轻量轮：finalize 的退出码不得把"兄弟 capture 未关闭"误报成本次失败。"""

    def _tiny_png(self, path: Path) -> None:
        def chunk(tag: bytes, data: bytes) -> bytes:
            piece = struct.pack(">I", len(data)) + tag + data
            return piece + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))

    def _sandbox(self) -> Path:
        sys.path.insert(0, str(ROOT / "tests"))
        from _fixture import make_temp_repo
        root = make_temp_repo(Path(tempfile.mkdtemp(prefix="pu-multicap-")))
        (root / "memory" / "branches" / "domain.games.md").write_text("---\nid: domain.games\nkind: entity\nstatus: current\ntitle: 游戏\n---\n\n# 游戏\n", encoding="utf-8")
        return root

    def _run(self, root: Path, *args: str) -> tuple[int, str, str]:
        proc = subprocess.run([sys.executable, str(root / "scripts" / args[0]), *args[1:]], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def test_finalize_exit_code_is_zero_while_sibling_capture_is_still_pending(self):
        root = self._sandbox()
        text = "看看我截的这个游戏截图，弦一郎这关怎么打？"
        self._run(root, "preflight_context.py", text, "--turn-id", "turn.multi.reg", "--tier", "light", "--root", str(root))
        self.assertEqual(self._run(root, "capture_user_update.py", "--text", text, "--capture-id", "cap.reg.text", "--turn-id", "turn.multi.reg")[0], 0)
        img = root / "shot.png"; self._tiny_png(img)
        self.assertEqual(self._run(root, "capture_attachment.py", "--file", str(img), "--capture-id", "cap.reg.img", "--turn-id", "turn.multi.reg")[0], 0)
        sys.path.insert(0, str(root / "scripts"))
        import mcp_server
        result = mcp_server.add_record({"id": "state.current.playing-sekiro-reg", "kind": "state", "domain": "domain.games",
            "summary": "2026-09 正在玩《只狼》，卡在弦一郎。", "tier": "light", "salience": 1,
            "capture_id": "cap.reg.text", "verbatim_refs": "cap.reg.text;cap.reg.img"})
        self.assertNotIn("拒绝写入", result["content"][0]["text"])
        # §6.1: the write succeeded while cap.reg.text/img are still pending (normal
        # mid-turn state); it must NOT be reported as isError, or the model retries
        # and duplicates the record.
        self.assertFalse(result["isError"], result["content"][0]["text"])
        rc1, out1, err1 = self._run(root, "finalize_capture.py", "--capture-id", "cap.reg.text", "--disposition", "derived", "--reason", "正文闭环")
        self.assertEqual(rc1, 0, f"first finalize must not fail on sibling pending: rc={rc1} err={err1} out={out1[:200]}")
        rc2, _, err2 = self._run(root, "finalize_capture.py", "--capture-id", "cap.reg.img", "--disposition", "derived", "--reason", "附件归档")
        self.assertEqual(rc2, 0, err2)
        rc3, out3, _ = self._run(root, "session_check.py", "--turn-id", "turn.multi.reg", "--allow-warnings")
        self.assertEqual(rc3, 0, out3)
        self.assertTrue(json.loads(out3)["may_claim_memory_updated"])


if __name__ == "__main__":
    unittest.main()
