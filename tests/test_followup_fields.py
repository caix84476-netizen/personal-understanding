"""Followup source/expiry completeness: the followup policy wants every entry to
carry source refs and an expiry rule. The write path reminds (never refuses —
hard constraint #1); review_v2 flags open entries as an audit warning."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from v2_archive import loose_followup_fields, loose_followups  # noqa: E402


class LooseFollowupFieldTests(unittest.TestCase):
    def test_complete_row_lists_nothing(self):
        row = {"id": "f1", "source_refs": ["capture-1"], "due_at": "2026-09-10", "due_rule": "fixed-date"}
        self.assertEqual(loose_followup_fields(row), [])

    def test_missing_source_and_expiry_lists_both(self):
        self.assertEqual(loose_followup_fields({"id": "f2"}), ["source_refs（来源）", "due_at/due_rule（到期规则）"])

    def test_explicit_rule_without_date_counts_as_scheduled(self):
        # The MCP default (next-relevant-activation) is a rule; a caller passing it
        # explicitly is only reminded about the source, not the expiry.
        self.assertEqual(loose_followup_fields({"id": "f3", "due_rule": "next-relevant-activation"}), ["source_refs（来源）"])


class LooseFollowupsTests(unittest.TestCase):
    def test_only_open_rows_are_flagged(self):
        rows = [
            {"id": "open-loose", "status": "pending"},
            {"id": "closed-loose", "status": "answered"},
            {"id": "open-complete", "status": "pending", "source_refs": ["s"], "due_at": "2026-01-01"},
        ]
        self.assertEqual(loose_followups(rows), ["open-loose"])

    def test_status_defaults_to_pending(self):
        self.assertEqual(loose_followups([{"id": "bare"}]), ["bare"])


if __name__ == "__main__":
    unittest.main()
