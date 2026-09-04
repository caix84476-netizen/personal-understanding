"""Weighted retrieval ranking (2.4.1): IDF term weights, length normalization,
entity-first selection, and the recall cases that motivated the fix.

Unit tests run anywhere; the integration tests exercise the real archive and
skip when memory/v2 is absent.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from catalog_utils import term_weights, weighted_match_score, weighted_query_terms

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()


class WeightedTokenizerTests(unittest.TestCase):
    def test_single_chars_dropped_from_multi_char_runs(self):
        terms = weighted_query_terms("只狼 打法")
        self.assertIn("只狼", terms)
        self.assertIn("打法", terms)
        self.assertNotIn("只", terms)
        self.assertNotIn("狼", terms)

    def test_standalone_single_char_kept(self):
        self.assertIn("钱", weighted_query_terms("钱"))

    def test_latin_tokens_kept(self):
        terms = weighted_query_terms("CS2 steam 愿望单")
        self.assertIn("cs2", terms)
        self.assertIn("steam", terms)
        self.assertIn("愿望单", terms)


class TermWeightTests(unittest.TestCase):
    def test_rare_term_outranks_common_term(self):
        docs = ["只狼 在 玩 游戏"] * 10 + ["在 玩 游戏 在 玩 游戏"] * 90
        weights = term_weights(["只狼", "在"], docs)
        self.assertGreater(weights["只狼"], weights["在"])

    def test_single_char_weight_near_noise(self):
        docs = ["哥哥在家", "妈妈在家", "在家吃饭"]
        weights = term_weights(["哥", "在"], docs)
        self.assertLess(weights["在"], 1.0)


class WeightedMatchScoreTests(unittest.TestCase):
    def test_length_normalization_stops_long_docs_dominating(self):
        weights = {"只狼": 5.0, "在": 0.1}
        short = weighted_match_score("只狼 打法", weights)
        long = weighted_match_score("只狼 打法 " + "在" * 2000, weights)
        self.assertGreater(short, long)

    def test_empty_query_scores_zero(self):
        self.assertEqual(weighted_match_score("任意文本", {}), 0.0)


@unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
class RecallRegressionTests(unittest.TestCase):
    """The five documented failure cases must now hit their targets."""

    def run_probe(self, query):
        result = subprocess.run([sys.executable, str(SCRIPTS / "retrieve_v2.py"), "--maintenance", "--query", query, "--level", "probe", "--format", "json", "--no-trace"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_sekiro_entity_and_games_card_recalled(self):
        data = self.run_probe("只狼 Sekiro 弦一郎 在玩 打法")
        entity_ids = [row.get("id") for row in data["entities"]]
        self.assertIn("entity.game.sekiro", entity_ids[:3])
        knowledge_ids = [row.get("record_id") for row in data["knowledge"]]
        self.assertIn("fact.interests.games-detailed-20260809", knowledge_ids[:3])

    def test_witcher3_card_recalled(self):
        data = self.run_probe("巫师3 在玩 猫学派")
        knowledge_ids = [row.get("record_id") for row in data["knowledge"]]
        self.assertIn("fact.games.witcher3-feel-anchored-by-rdr2-20260830", knowledge_ids[:3])

    def test_home_noise_recalled_for_roommate_query(self):
        data = self.run_probe("室友 冲突 噪音 哥哥 家里")
        record_ids = [row.get("record_id") for row in data["timeline"]]
        self.assertIn("state.current.home-noise", record_ids[:5])

    def test_privacy_rule_recalled(self):
        data = self.run_probe("隐私 档案 给别人看 AI 记性")
        knowledge_ids = [row.get("record_id") for row in data["knowledge"]]
        self.assertIn("correction.meta.privacy-normalized-20260829", knowledge_ids[:5])

    def test_positive_controls_stay_first(self):
        for query, target in (("四级 英语 学习策略 词汇", "decision.education.university-study-strategy-20260820"), ("贷款 12月 到账 新生须知", "state.education.notice-payment-bus-bingyi-details-20260903")):
            data = self.run_probe(query)
            record_ids = [row.get("record_id") for row in data["timeline"]]
            self.assertIn(target, record_ids[:2], f"{query} lost its positive control")


if __name__ == "__main__":
    unittest.main()
