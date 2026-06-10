"""Tests for gen_keywords.py — a names list → custom_keywords YAML formatter.

Input: a markdown/text file with `# PREFIX` group headers; one person per line;
comma-separated aliases on a line all share that person's two-digit code.

All names below are synthetic placeholders (this file is published).

    .venv/bin/python -m unittest tests.test_gen_keywords -v
Stdlib-only — runs under system python3 too.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gen_keywords


def fmt(text):
    return gen_keywords.format_keywords(text)


class TestGenKeywords(unittest.TestCase):
    def test_basic_per_person_numbering(self):
        out, warns = fmt("# ENG\nMary Bello\nJohn Smith\n")
        # Pin the 2-space indent so output pastes straight under `custom_keywords:`.
        self.assertIn('  - find: "Mary Bello"\n    replace: "ENG01"', out)
        self.assertIn('  - find: "John Smith"\n    replace: "ENG02"', out)
        self.assertEqual(warns, [])

    def test_aliases_share_one_code(self):
        out, _ = fmt("# ENG\nMary, Mary Bello\nJohn Smith\n")
        self.assertIn('  - find: "Mary"\n    replace: "ENG01"', out)
        self.assertIn('  - find: "Mary Bello"\n    replace: "ENG01"', out)  # same code
        self.assertIn('  - find: "John Smith"\n    replace: "ENG02"', out)   # next person

    def test_per_group_reset(self):
        out, _ = fmt("# ENG\nMary Bello\n# MGR\nJohn Smith\n")
        self.assertIn('  - find: "Mary Bello"\n    replace: "ENG01"', out)
        self.assertIn('  - find: "John Smith"\n    replace: "MGR01"', out)

    def test_two_digit_padding(self):
        names = "\n".join(f"P{i}" for i in range(1, 11))   # 10 synthetic people
        out, _ = fmt("# X\n" + names + "\n")
        self.assertIn('replace: "X01"', out)
        self.assertIn('replace: "X09"', out)
        self.assertIn('replace: "X10"', out)

    def test_strips_bullets_and_blank_lines(self):
        out, _ = fmt("# ENG\n\n- Mary Bello\n* John Smith\n")
        self.assertIn('- find: "Mary Bello"', out)
        self.assertIn('- find: "John Smith"', out)
        self.assertNotIn('"- Mary Bello"', out)

    def test_quote_escaping(self):
        out, _ = fmt('# ENG\nJo "Doe"\n')
        self.assertIn(r'- find: "Jo \"Doe\""', out)   # JSON-style escaping (valid YAML)

    def test_duplicate_find_warns_but_still_emits(self):
        out, warns = fmt("# ENG\nMary Bello\n# MGR\nmary bello\n")   # case-insensitive dup
        self.assertTrue(any("duplicate" in w.lower() for w in warns), warns)
        self.assertIn('- find: "mary bello"', out)   # emitted anyway, so the user can fix it

    def test_comma_in_name_splits_known_limitation(self):
        # Comma is the alias delimiter, so "Doe, John" is two aliases of ONE person
        # (both X01) — intended trade-off of choosing comma over a rarer delimiter.
        out, _ = fmt("# X\nDoe, John\n")
        self.assertIn('  - find: "Doe"\n    replace: "X01"', out)
        self.assertIn('  - find: "John"\n    replace: "X01"', out)

    def test_name_before_header_warns_and_skips(self):
        out, warns = fmt("Mary Bello\n# ENG\nJohn Smith\n")
        self.assertTrue(any("Mary Bello" in w for w in warns), warns)
        self.assertNotIn('- find: "Mary Bello"', out)                  # skipped
        self.assertIn('- find: "John Smith"\n    replace: "ENG01"', out)   # still works


if __name__ == "__main__":
    unittest.main()
