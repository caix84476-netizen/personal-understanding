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

from catalog_utils import content_terms, single_char_aliases, term_weights, weighted_match_score, weighted_query_terms

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

    def test_alias_single_char_keeps_multi_char_weight(self):
        # §4.2: a curated 1-char entity alias (妈) must NOT be demoted to noise;
        # a stray single char (在) still is. Same docs, same terms — only the
        # alias set changes the outcome.
        docs = ["妈妈在家", "在家吃饭", "他在学校"]
        weights_noise = term_weights(["妈", "在"], docs)
        weights_alias = term_weights(["妈", "在"], docs, single_char_aliases([{"aliases": ["妈"]}]))
        self.assertGreater(weights_alias["妈"], weights_noise["妈"])
        self.assertAlmostEqual(weights_alias["在"], weights_noise["在"])

    def test_single_char_aliases_only_collects_cjk_singles(self):
        aliases = single_char_aliases([
            {"aliases": ["妈", "mother", "母亲"]},
            {"aliases": ["她"]},
            {"aliases": []},
        ])
        self.assertEqual(aliases, {"妈", "她"})

    def test_content_terms_excludes_non_alias_singles(self):
        content = content_terms(["只狼", "防", "妈"], {"妈"})
        self.assertEqual(content, {"只狼", "妈"})
        # a query with no content terms at all demands nothing (all records pass)
        self.assertEqual(content_terms(["防"], set()), set())

    def test_closed_class_function_words_are_never_content(self):
        # 怎么 is rare in a strategy-free archive but referentially empty; IDF would
        # score it like a proper noun. It must be excluded from content terms even
        # at 2 chars, and demoted in weight like noise.
        from catalog_utils import STOP_TERMS
        self.assertNotIn("怎么", content_terms(["只狼", "怎么"], set()))
        self.assertIn("怎么", STOP_TERMS)
        docs = ["怎么 这样"] * 5 + ["只狼 弦一郎"] * 95  # 怎么 rarer than a real term
        # 2.6.0 lexicon demotion reads the real archive lexicon; blank it out so
        # this unit test measures the pure corpus statistics it was written for.
        from unittest import mock
        with mock.patch("lexicon.known", return_value=False):
            weights = term_weights(["怎么", "弦一郎"], docs)
        # both OOV under the blanked lexicon: STOP ×0.15×0.4 must stay below the
        # multi-char bonus ×1.3×0.4 — closed-class words never anchor ranking.
        self.assertLess(weights["怎么"], weights["弦一郎"])

    def test_lexicon_oov_slices_are_demoted_but_keep_recall(self):
        # 2.6.0: cross-word accident slices (郎我) are OOV everywhere and must not
        # out-anchor a dictionary-known decisive term, while still carrying weight
        # (recall is never deleted; a sole hit still wins a relative ranking).
        from unittest import mock
        # same document frequency for the OOV slice and the known term, so the
        # assertion isolates the ×0.4 demotion instead of raw IDF differences.
        docs = ["郎我卡了 打法 弦一郎"] * 10 + ["别的 东西"] * 90
        with mock.patch("lexicon.known", side_effect=lambda t: t == "打法"):
            weights = term_weights(["郎我卡了", "弦一郎", "打法"], docs)
        self.assertLess(weights["郎我卡了"], weights["打法"], "equal-df OOV slice must weigh below a dictionary term")
        self.assertLess(weights["弦一郎"], weights["打法"])
        self.assertGreater(weights["郎我卡了"], 0, "OOV demotion keeps recall (never zero)")

    def test_mixed_proper_noun_terms_survive_tokenization(self):
        # 2.6.0: CJK/Latin boundary must not split the sharpest anchor (巫师3, 晕3D).
        terms = weighted_query_terms("巫师3 骑马 手感")
        self.assertIn("巫师3", terms)
        terms2 = weighted_query_terms("晕3D 艾迪芬奇")
        self.assertIn("晕3d", terms2)
        # and the stray single char must not qualify content on its own
        self.assertNotIn("3", content_terms(terms, set()))


class DeepSeedPriorityTests(unittest.TestCase):
    # 2.5.0 §5.2: a record explicitly requested for deep verification must surface
    # its own fragments before any neighbor verbatim, even when its evidence is
    # summary_only — otherwise the 40-slot budget answers a different record.
    @unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/v2)")
    def test_seed_summary_only_fragment_outranks_neighbor_verbatim(self):
        data = subprocess.run([sys.executable, str(SCRIPTS / "retrieve_v2.py"), "--maintenance", "--query", "家里 噪音",
                               "--level", "deep", "--event-ids", "entry.state.current.home-noise", "--format", "json", "--no-trace"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(data.returncode, 0, data.stderr)
        fragments = json.loads(data.stdout)["fragments"]
        self.assertTrue(fragments)
        self.assertEqual(fragments[0]["id"], "fragment.legacy.state.current.home-noise",
                         "the queried record's own summary_only fragment must lead the deep output")


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


class RecencyFactorTests(unittest.TestCase):
    """2.6.1 §4c: Generative-Agents multiplicative recency on the lexical channel.
    Unit-level contract (runs anywhere — no archive needed)."""

    def test_undated_record_is_neutral_not_ancient(self):
        # the measured regression: treating missing dates as ancient silently
        # buried correctly-titled records; undated must stay at full weight
        from catalog_utils import recency_factor
        from datetime import date
        self.assertEqual(recency_factor({"date_start": ""}, today=date(2026, 9, 5)), 1.0)
        self.assertEqual(recency_factor({}, today=date(2026, 9, 5)), 1.0)
        self.assertEqual(recency_factor({"date_start": "not-a-date"}, today=date(2026, 9, 5)), 1.0)

    def test_half_life_halves_the_score(self):
        from catalog_utils import recency_factor, RECENCY_HALF_LIFE_DAYS
        from datetime import date, timedelta
        today = date(2026, 9, 5)
        one_half_life = {"date_start": (today - timedelta(days=RECENCY_HALF_LIFE_DAYS)).isoformat()}
        self.assertAlmostEqual(recency_factor(one_half_life, today=today), 0.5, places=6)
        self.assertAlmostEqual(recency_factor({"date_start": "2026-09-05"}, today=today), 1.0)
        two_half_lives = {"date_start": (today - timedelta(days=2 * RECENCY_HALF_LIFE_DAYS)).isoformat()}
        self.assertAlmostEqual(recency_factor(two_half_lives, today=today), 0.25, places=6)

    def test_newer_record_outranks_older_all_else_equal(self):
        from catalog_utils import recency_factor
        from datetime import date
        today = date(2026, 9, 5)
        self.assertGreater(recency_factor({"date_start": "2026-08-19"}, today=today),
                           recency_factor({"date_start": "2026-07-15"}, today=today))

    def test_future_or_past_today_no_negative_age(self):
        from catalog_utils import recency_factor
        from datetime import date
        # age clamps at 0 → newest weight 1.0 even if the date is after "today"
        self.assertLessEqual(recency_factor({"date_start": "2027-01-01"}, today=date(2026, 9, 5)), 1.0)


@unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
class TimeConsistencyRecallTests(unittest.TestCase):
    """The §4c gold contract on the real archive: for two records about one matter
    spanning a month, the fresher must not be buried below the older one."""

    def run_probe(self, query):
        result = subprocess.run([sys.executable, str(SCRIPTS / "retrieve_v2.py"), "--maintenance", "--query", query, "--level", "probe", "--format", "json", "--no-trace"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_entity_home_recent_state_outranks_old_intake(self):
        # source.intake.2026-07-15 (old, entity home) vs home-social-pattern-20260719…:
        # under recency the current-state records lead; the July intake drops back
        data = self.run_probe("家庭交流现在的模式")
        ids = [row.get("record_id") or row.get("id") for row in data["timeline"]]
        recent = next((i for i in ids if i and ("home-social-pattern" in i or "transition-overload" in i)), None)
        intake = next((i for i in ids if i and i == "source.intake.2026-07-15"), None)
        if recent and intake:
            self.assertLess(ids.index(recent), ids.index(intake))

    def test_h16_lawsuit_house_reaches_lexical_top(self):
        # the §4b+§4c combined contract: zero query-term overlap record reaches the
        # timeline via entity boost + recency AND keeps its labeled associative path
        data = self.run_probe("我爸又来电话说房子的事")
        ids = [row.get("record_id") or row.get("id") for row in data["timeline"]]
        self.assertIn("event.family.parents-lawsuit-house-rent-20260903", ids[:5])
        assoc = [row.get("record_id") for row in data["associations"]]
        self.assertIn("event.family.parents-lawsuit-house-rent-20260903", assoc)


if __name__ == "__main__":
    unittest.main()
