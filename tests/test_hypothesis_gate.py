"""Causal-hypothesis gate: 普通事实问题不自动加载因果假设（SKILL.md 因果假设政策）。

Retrieval-layer engineering (catalog_utils.select_hypotheses): a hypothesis's
claim/scope/mechanism travels only when the query's content terms hit its text.
The catalog shows claim-less stubs otherwise; --view full bypasses the gate.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from catalog_utils import content_terms, select_hypotheses, weighted_query_terms  # noqa: E402

HAS_ARCHIVE = (ROOT / "memory" / "v2").is_dir()
HAS_HYPOTHESES = HAS_ARCHIVE and (ROOT / "memory" / "v2" / "hypotheses.jsonl").is_file()

HYPOTHESIS = {
    "id": "hypothesis.test.open-choice-avoidance",
    "kind": "causal_hypothesis",
    "status": "candidate",
    "claim": "在低风险日常事务中，用户可能因不确定性叠加而提高行动启动门槛。",
    "scope": "当前暑假、日用品购买、开学准备和低难度待办；不外推为稳定人格。",
    "mechanism": "开放选择触发多重评估，评估未收敛前暂停行动。",
    "alternatives": ["单纯缺乏稳定的日常流程脚本"],
    "supports": ["state.current.some-record"],
    "confidence": "low",
}


def gate(query: str, rows: list[dict]) -> list[dict]:
    terms = weighted_query_terms(query)
    return select_hypotheses(rows, terms, content_terms(terms, frozenset()))


class SelectHypothesesUnitTests(unittest.TestCase):
    def test_causal_query_carries_matching_hypothesis(self):
        matched = gate("为什么买日用品总是拖延不动手", [dict(HYPOTHESIS)])
        self.assertEqual([row["id"] for row in matched], [HYPOTHESIS["id"]])

    def test_function_word_only_query_loads_nothing(self):
        # 怎么/为什么 are STOP_TERMS; a lone 办 is not a content term either.
        self.assertEqual(gate("怎么办 为什么", [dict(HYPOTHESIS)]), [])

    def test_factual_query_with_no_textual_overlap_loads_nothing(self):
        self.assertEqual(gate("只狼 弦一郎 突刺 怎么防", [dict(HYPOTHESIS)]), [])

    def test_empty_query_loads_nothing(self):
        self.assertEqual(gate("", [dict(HYPOTHESIS)]), [])

    def test_cap_limits_carried_rows(self):
        rows = []
        for index in range(8):
            row = dict(HYPOTHESIS)
            row["id"] = f"hypothesis.test.row-{index}"
            row["claim"] = f"关于拖延的因果解释 {index}"
            rows.append(row)
        self.assertEqual(len(gate("拖延的因果解释是什么", rows)), 6)

    def test_higher_confidence_wins_ties(self):
        low = dict(HYPOTHESIS, id="hypothesis.test.low", confidence="low")
        high = dict(HYPOTHESIS, id="hypothesis.test.high", confidence="high")
        matched = gate("为什么买日用品总是拖延不动手", [low, high])
        self.assertEqual(matched[0]["id"], "hypothesis.test.high")

    def test_stop_term_hit_alone_does_not_qualify(self):
        # The row's text contains the STOP word 怎么; a query whose only shared
        # tokens are that STOP word (plus non-matching fragments) must not
        # qualify it — the T02 survivor class: a 只狼 strategy query pulling
        # in records that merely happen to say 怎么.
        row = dict(HYPOTHESIS, claim="想搞清楚自己怎么就搁置了。", scope="日用品购买。",
                   mechanism="评估超时即搁置。", alternatives=[], supports=[])
        self.assertEqual(gate("只狼 怎么防", [row]), [])


@unittest.skipUnless(HAS_ARCHIVE, "requires an initialized archive (memory/)")
class GateIntegrationTests(unittest.TestCase):
    def run_script(self, name: str, *args: str):
        # Reads in tests are non-conversational maintenance reads; the capture
        # gate would otherwise reject them (§6.5 maintenance key).
        if name in ("retrieve_v2.py", "catalog_context.py"):
            args = ("--maintenance", *args)
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    @unittest.skipUnless(HAS_HYPOTHESES, "requires hypotheses.jsonl")
    def test_retrieve_factual_query_carries_no_hypotheses(self):
        result = self.run_script("retrieve_v2.py", "--no-trace", "--query", "只狼 弦一郎 突刺 怎么防", "--level", "probe")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["hypotheses"], [])
        self.assertGreaterEqual(payload["trace"]["hypotheses"]["omitted"], 1)

    def test_catalog_survey_without_query_shows_claim_less_stubs(self):
        result = self.run_script("catalog_context.py", "--view", "survey")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for row in json.loads(result.stdout)["v2"]["hypotheses"]:
            self.assertNotIn("claim", row)
            self.assertIn("status", row)

    @unittest.skipUnless(HAS_HYPOTHESES, "requires hypotheses.jsonl")
    def test_catalog_survey_factual_query_shows_claim_less_stubs(self):
        result = self.run_script("catalog_context.py", "--view", "survey", "--query", "只狼 弦一郎 突刺")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for row in json.loads(result.stdout)["v2"]["hypotheses"]:
            self.assertNotIn("claim", row)

    def test_catalog_full_view_bypasses_the_gate(self):
        result = self.run_script("catalog_context.py", "--view", "full")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = json.loads(result.stdout)["v2"]["hypotheses"]
        if not rows:
            self.skipTest("archive has no hypotheses")
        for row in rows:
            self.assertIn("claim", row)


if __name__ == "__main__":
    unittest.main()
