import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keyword_redactor import KeywordRedactor, load_mappings


class TestRedact(unittest.TestCase):
    def test_single_keyword_swapped(self):
        r = KeywordRedactor([{"find": "Mary", "replace": "[PERSON_A]"}])
        self.assertEqual(r.redact("met Mary today"), "met [PERSON_A] today")

    def test_case_insensitive(self):
        r = KeywordRedactor([{"find": "Mary", "replace": "[A]"}])
        self.assertEqual(r.redact("MARY and mary"), "[A] and [A]")

    def test_word_boundary(self):
        r = KeywordRedactor([{"find": "Mary", "replace": "[A]"}])
        self.assertEqual(r.redact("Maryland"), "Maryland")  # substring untouched

    def test_longest_match_first(self):
        r = KeywordRedactor([
            {"find": "Mary", "replace": "[FIRST]"},
            {"find": "Mary Bello", "replace": "[FULL]"},
        ])
        self.assertEqual(r.redact("Mary Bello and Mary"), "[FULL] and [FIRST]")

    def test_counts_per_find_accumulate(self):
        r = KeywordRedactor([{"find": "Mary", "replace": "[A]"}])
        r.redact("Mary saw Mary")
        r.redact("Mary again")
        self.assertEqual(r.counts["Mary"], 3)

    def test_empty_mappings_noop(self):
        r = KeywordRedactor([])
        self.assertEqual(r.redact("nothing changes"), "nothing changes")

    def test_replacement_not_rematched(self):
        # 'Chen' must NOT eat the output of the 'Alice Chen' swap (single pass)
        r = KeywordRedactor([{"find": "Alice Chen", "replace": "[PERSON_A]"},
                             {"find": "Chen", "replace": "[SURNAME]"}])
        self.assertEqual(r.redact("Alice Chen"), "[PERSON_A]")

    def test_shared_replace_aliases_both(self):
        # two finds -> one pseudonym; both redact, counts tracked per find
        r = KeywordRedactor([{"find": "Mary", "replace": "[PERSON_A]"},
                             {"find": "Mary Bello", "replace": "[PERSON_A]"}])
        self.assertEqual(r.redact("Mary Bello met Mary"), "[PERSON_A] met [PERSON_A]")
        self.assertEqual(r.counts["Mary Bello"], 1)
        self.assertEqual(r.counts["Mary"], 1)


class TestLoadMappings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, obj):
        p = self.tmp / "m.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def test_valid_returns_list(self):
        p = self._write([{"find": "Mary", "replace": "[A]"}])
        self.assertEqual(load_mappings(p), [{"find": "Mary", "replace": "[A]"}])

    def test_not_a_list_raises(self):
        p = self._write({"find": "x", "replace": "y"})
        with self.assertRaises(ValueError):
            load_mappings(p)

    def test_empty_or_missing_fields_raise(self):
        for bad in ([{"find": "", "replace": "[A]"}],
                    [{"find": "Mary"}],
                    [{"find": "Mary", "replace": ""}]):
            with self.subTest(bad=bad):
                p = self._write(bad)
                with self.assertRaises(ValueError):
                    load_mappings(p)

    def test_duplicate_find_case_insensitive_raises(self):
        p = self._write([{"find": "Mary", "replace": "[A]"},
                         {"find": "mary", "replace": "[B]"}])
        with self.assertRaises(ValueError):
            load_mappings(p)

    def test_shared_replace_allowed_with_warning(self):
        # aliasing many mentions of one person to one pseudonym is valid
        p = self._write([{"find": "Mary", "replace": "[PERSON_A]"},
                         {"find": "Mary Bello", "replace": "[PERSON_A]"}])
        with self.assertWarns(UserWarning):
            result = load_mappings(p)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
