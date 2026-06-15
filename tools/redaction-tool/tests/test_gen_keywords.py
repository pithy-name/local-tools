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


class TestBlackoutGroup(unittest.TestCase):
    """The reserved `# BLACKOUT` group emits PLAIN strings (-> █████), no codes.
    Synthetic placeholders only (published file)."""

    def test_blackout_emits_plain_string_no_code(self):
        out, warns = fmt("# BLACKOUT\nMain Street Clinic\n")
        self.assertIn('  - "Main Street Clinic"', out)   # plain string, 2-space indent
        self.assertNotIn("find:", out)                   # no find/replace for blackout
        self.assertNotIn("replace:", out)
        self.assertEqual(warns, [])

    def test_blackout_commas_are_separate_terms(self):
        # Contrast with pseudonym groups: in BLACKOUT, comma = SEPARATE terms,
        # not aliases-of-one (blackout has no code to share).
        out, _ = fmt("# BLACKOUT\nFirst Ave, Second Ave, Third Ave\n")
        self.assertIn('  - "First Ave"', out)
        self.assertIn('  - "Second Ave"', out)
        self.assertIn('  - "Third Ave"', out)
        self.assertNotIn("replace:", out)

    def test_blackout_header_case_insensitive(self):
        out, _ = fmt("# blackout\nSomeplace Hall\n")
        self.assertIn('  - "Someplace Hall"', out)

    def test_blackout_multiple_lines(self):
        out, _ = fmt("# BLACKOUT\nAlpha\nBeta, Gamma\n")
        for term in ("Alpha", "Beta", "Gamma"):
            self.assertIn(f'  - "{term}"', out)

    def test_blackout_and_pseudonym_groups_coexist(self):
        out, _ = fmt("# ENG\nMary Bello\n# BLACKOUT\nAcme Plaza, Beta Tower\n")
        self.assertIn('  - find: "Mary Bello"\n    replace: "ENG01"', out)  # pseudonym intact
        self.assertIn('  - "Acme Plaza"', out)                             # blackout plain
        self.assertIn('  - "Beta Tower"', out)

    def test_blackout_quote_escaping(self):
        out, _ = fmt('# BLACKOUT\nThe "Spot"\n')
        self.assertIn(r'  - "The \"Spot\""', out)   # JSON-style escaping (valid YAML)


class TestSpliceIntoConfig(unittest.TestCase):
    """`--write` core: replace the keyword block between managed markers in place.
    Pure string-in/string-out; synthetic data only."""

    BEGIN = "  # >>> gen_keywords:begin >>>"
    END = "  # <<< gen_keywords:end <<<"

    def _cfg(self, middle):
        return ("custom_keywords:\n"
                f"{self.BEGIN}\n"
                f"{middle}\n"
                f"{self.END}\n"
                'replacement: "X"\n')

    def test_replaces_between_markers(self):
        new = gen_keywords.splice_into_config(self._cfg('  - "OLD"'), '  - "NEW"')
        self.assertIn('  - "NEW"', new)
        self.assertNotIn('"OLD"', new)

    def test_preserves_surrounding_and_markers(self):
        new = gen_keywords.splice_into_config(self._cfg('  - "OLD"'), '  - "NEW"')
        self.assertTrue(new.startswith("custom_keywords:\n"))   # before-begin kept
        self.assertIn('replacement: "X"', new)                   # after-end kept
        self.assertIn("gen_keywords:begin", new)                 # markers retained
        self.assertIn("gen_keywords:end", new)

    def test_missing_markers_raises_valueerror(self):
        with self.assertRaises(ValueError):
            gen_keywords.splice_into_config('custom_keywords:\n  - "X"\n', '  - "NEW"')


class TestUpdateConfigFile(unittest.TestCase):
    """`--write` I/O wrapper: writes between markers, makes a .bak, atomic."""

    def test_writes_between_markers_and_backs_up(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text(
                'custom_keywords:\n'
                '  # >>> gen_keywords:begin >>>\n'
                '  - "OLD"\n'
                '  # <<< gen_keywords:end <<<\n'
                'replacement: "X"\n', encoding="utf-8")
            gen_keywords.update_config_file(str(p), '  - "NEW"')
            txt = p.read_text(encoding="utf-8")
            self.assertIn('  - "NEW"', txt)
            self.assertNotIn('"OLD"', txt)
            self.assertTrue((Path(d) / "config.yaml.bak").exists())   # backup made
            self.assertIn('"OLD"', (Path(d) / "config.yaml.bak").read_text())  # .bak = original


class TestFindDuplicateFinds(unittest.TestCase):
    """find_duplicate_finds(text) -> sorted lowercased find-terms that occur 2+ times
    (the same dup key gen_keywords/the redactor use). Empty list = clean. Synthetic only."""

    def test_clean_has_no_dupes(self):
        self.assertEqual(gen_keywords.find_duplicate_finds("# ENG\nMary Bello\nJohn Smith\n"), [])

    def test_exact_repeat_same_group(self):
        self.assertEqual(
            gen_keywords.find_duplicate_finds("# ENG\nMary Bello\nMary Bello\n"), ["mary bello"])

    def test_cross_group_same_term(self):
        # same name under two prefixes → would map to two different codes (real conflict)
        self.assertEqual(
            gen_keywords.find_duplicate_finds("# ENG\nMary Bello\n# MGR\nMary Bello\n"),
            ["mary bello"])

    def test_blackout_repeat(self):
        # in BLACKOUT, commas are independent terms; the repeat is a dup
        self.assertEqual(gen_keywords.find_duplicate_finds("# BLACKOUT\nAcme, Acme\n"), ["acme"])

    def test_alias_vs_standalone(self):
        self.assertEqual(
            gen_keywords.find_duplicate_finds("# ENG\nMary, Mary Bello\n# MGR\nMary\n"), ["mary"])

    def test_case_insensitive(self):
        self.assertEqual(
            gen_keywords.find_duplicate_finds("# ENG\nMary Bello\n# MGR\nmary bello\n"),
            ["mary bello"])

    def test_multiple_dupes_sorted(self):
        out = gen_keywords.find_duplicate_finds(
            "# ENG\nMary Bello\nMary Bello\n# MGR\nJohn Smith\nJohn Smith\n")
        self.assertEqual(out, ["john smith", "mary bello"])


if __name__ == "__main__":
    unittest.main()
