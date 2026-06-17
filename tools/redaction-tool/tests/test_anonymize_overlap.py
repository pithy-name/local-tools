"""T2.1 regression: anonymize must de-overlap spans before replacing.

Presidio can return overlapping spans (e.g. KW_0 "Acme" 0:4 AND ORGANIZATION
"Acme Corporation" 0:16). The current high→low slice-replacement applies the longer
span first, then the shorter span overwrites already-mutated indices with stale offsets
→ part of the redaction is lost AND adjacent real text is destroyed.

Fix: drop/merge spans contained within a longer/higher-scoring span, then replace
the surviving non-overlapping spans.

    .venv/bin/python -m unittest tests.test_anonymize_overlap -v
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _span(start, end, entity_type):
    r = MagicMock()
    r.start = start
    r.end = end
    r.entity_type = entity_type
    return r


class TestAnonymizeOverlap(unittest.TestCase):
    def test_contained_kw_dropped_outer_wins(self):
        """KW_0 (0:4) contained in ORG (0:16) → outer span wins, no corruption."""
        text = "Acme Corporation went public"
        r_org = _span(0, 16, "ORGANIZATION")
        r_kw = _span(0, 4, "KW_0")
        result = redact.anonymize(text, [r_org, r_kw], "█████", {"KW_0": "[C]"})
        self.assertEqual(result, "█████ went public")
        self.assertNotIn("[C]", result, "contained KW span must be dropped")

    def test_non_overlapping_spans_both_applied(self):
        """Two non-overlapping spans must both be replaced."""
        text = "Alice met Bob yesterday"
        r_alice = _span(0, 5, "PERSON")
        r_bob = _span(10, 13, "PERSON")
        result = redact.anonymize(text, [r_alice, r_bob], "█████")
        self.assertEqual(result, "█████ met █████ yesterday")

    def test_single_span_unchanged(self):
        """Single span: no overlap logic needed, must still redact correctly."""
        text = "Call Marcus Webb today"
        r = _span(5, 16, "KW_0")
        result = redact.anonymize(text, [r], "█████", {"KW_0": "[P]"})
        self.assertEqual(result, "Call [P] today")

    def test_partial_overlap_keeps_longer(self):
        """Partially-overlapping spans: keep the longer one."""
        text = "John Smith Jr. was here"
        r_short = _span(0, 4, "PERSON")    # "John"
        r_long = _span(0, 14, "PERSON")    # "John Smith Jr."
        result = redact.anonymize(text, [r_short, r_long], "█████")
        self.assertEqual(result, "█████ was here")

    def test_adjacent_spans_not_merged(self):
        """Adjacent (touching but not overlapping) spans must both be applied."""
        text = "JohnSmith"
        r1 = _span(0, 4, "KW_0")   # "John"
        r2 = _span(4, 9, "KW_1")   # "Smith"
        result = redact.anonymize(text, [r1, r2], "█████", {"KW_0": "[A]", "KW_1": "[B]"})
        self.assertEqual(result, "[A][B]")


class TestRedactTextCount(unittest.TestCase):
    """Review finding: _redact_text returns len(results) before de-overlap, inflating
    total_redactions when overlapping spans are dropped by anonymize().
    """

    def test_redact_text_count_reflects_kept_spans_not_raw_results(self):
        """_redact_text must return the number of spans actually applied, not raw Presidio count."""
        from unittest.mock import patch

        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = ["ORGANIZATION"]
        cfg["custom_keywords"] = [{"find": "Acme", "replace": "[C]"}]
        analyzer, kw = redact.build_analyzer(cfg)

        # Overlapping: KW_0 "Acme" (0:4) contained in ORGANIZATION "Acme Corporation" (0:16)
        r_org = _span(0, 16, "ORGANIZATION")
        r_kw = _span(0, 4, "KW_0")
        # Raw results = 2; after de-overlap, kept = 1 (outer wins)
        with patch("redact.analyze", return_value=[r_org, r_kw]):
            _, count = redact._redact_text(
                "Acme Corporation went public", analyzer, cfg, kw, kr=None
            )

        self.assertEqual(count, 1,
                         "_redact_text must return len(kept) not len(results) when spans overlap")


if __name__ == "__main__":
    unittest.main()
