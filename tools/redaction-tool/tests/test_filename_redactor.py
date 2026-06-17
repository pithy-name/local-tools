"""Tests for filename_redactor.py — the stdlib substring filename-redaction engine.

Runs under system python3 (stdlib only). Mirrors test_keyword_redactor.py's layout.

Two key rules, both deliberate:
  1. SUBSTRING match (no \\b) — catches embedded terms like `asmith_1on1.png` that the
     word-boundary CONTENT engine leaves alone.
  2. ALIASED keywords only get RENAMED (→ their pseudonym). PLAIN (blackout) keywords are
     NOT renamed — they're only FLAGGED (a plain `█████`-style token is useless in a
     filename, and the user tracks identities by pseudonym). A plain keyword found in an
     output name is surfaced so it can be aliased or renamed by hand — never silently left.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from filename_redactor import (
    FilenameRedactor,
    sanitize_pseudonym,
    resolve_collisions,
    render_rename_map,
    plan_tree,
    summarize,
    collect_filename_flags,
    render_flags_file,
)

# replace="[X]" → aliased (renamed to pseudonym); replace=None → plain (flagged only).
# Same {find, replace} shape redact.py's normalize_keywords produces.
MAP = [
    {"find": "asmith", "replace": "[PERSON_A]"},
    {"find": "projectzeta", "replace": None},
]


class TestRedactString(unittest.TestCase):
    def test_embedded_substring_match_no_boundary(self):
        new, hits = FilenameRedactor(MAP).redact_dirname("asmith_1on1")
        self.assertEqual(new, "PERSON_A_1on1")
        self.assertEqual(hits, 1)

    def test_case_insensitive(self):
        new, _ = FilenameRedactor(MAP).redact_dirname("Asmith_notes")
        self.assertEqual(new, "PERSON_A_notes")

    def test_plain_keyword_is_not_substituted(self):
        # Plain (no-alias) keyword is NOT renamed — only flagged (see TestFlagging).
        new, hits = FilenameRedactor(MAP).redact_dirname("my_projectzeta_x")
        self.assertEqual(new, "my_projectzeta_x")
        self.assertEqual(hits, 0)

    def test_min_len_gate_skips_short_aliased(self):
        r = FilenameRedactor([{"find": "al", "replace": "[X]"}], min_len=4)
        new, hits = r.redact_dirname("alnotes")
        self.assertEqual(new, "alnotes")     # 'al' below threshold → not matched
        self.assertEqual(hits, 0)
        self.assertIn("al", r.skipped_short)

    def test_aliased_term_at_threshold_is_kept(self):
        r = FilenameRedactor([{"find": "alex", "replace": "[X]"}], min_len=4)
        new, _ = r.redact_dirname("alexnotes")
        self.assertEqual(new, "Xnotes")      # len('alex') == min_len → matched
        self.assertEqual(r.skipped_short, [])

    def test_longest_match_first(self):
        r = FilenameRedactor([
            {"find": "thanh", "replace": "[SHORT]"},
            {"find": "asmith", "replace": "[FULL]"},
        ])
        new, _ = r.redact_dirname("asmith")
        self.assertEqual(new, "FULL")

    def test_no_match_passthrough(self):
        new, hits = FilenameRedactor(MAP).redact_dirname("vacation_2024")
        self.assertEqual(new, "vacation_2024")
        self.assertEqual(hits, 0)


class TestFlagging(unittest.TestCase):
    def test_plain_keyword_is_flagged(self):
        self.assertEqual(
            FilenameRedactor(MAP).flagged_terms_in("notes/projectzeta_plan.txt"),
            ["projectzeta"])

    def test_aliased_keyword_is_not_flagged(self):
        # asmith has an alias → it gets renamed, not flagged.
        self.assertEqual(FilenameRedactor(MAP).flagged_terms_in("asmith_1on1"), [])

    def test_flag_is_case_insensitive(self):
        self.assertEqual(
            FilenameRedactor(MAP).flagged_terms_in("ProjectZeta_x"), ["projectzeta"])

    def test_flag_respects_min_len(self):
        r = FilenameRedactor([{"find": "zz", "replace": None}], min_len=4)
        self.assertEqual(r.flagged_terms_in("zz_file"), [])  # too short to flag
        self.assertIn("zz", r.skipped_short)


class TestSanitizePseudonym(unittest.TestCase):
    def test_strip_brackets(self):
        self.assertEqual(sanitize_pseudonym("[PERSON_A]"), "PERSON_A")

    def test_keep_dots_and_hyphens(self):
        self.assertEqual(sanitize_pseudonym("[CLIENT-A]"), "CLIENT-A")
        self.assertEqual(sanitize_pseudonym("J.S."), "J.S.")

    def test_space_to_underscore(self):
        self.assertEqual(sanitize_pseudonym("Client A"), "Client_A")


class TestRedactFilename(unittest.TestCase):
    def test_extension_preserved(self):
        new, hits = FilenameRedactor(MAP).redact_filename("asmith_1on1.png")
        self.assertEqual(new, "PERSON_A_1on1.png")
        self.assertEqual(hits, 1)

    def test_aliased_term_is_whole_stem(self):
        new, _ = FilenameRedactor([{"find": "report", "replace": "[R]"}]).redact_filename("report.txt")
        self.assertEqual(new, "R.txt")

    def test_no_extension_filename(self):
        new, _ = FilenameRedactor(MAP).redact_filename("asmith_README")
        self.assertEqual(new, "PERSON_A_README")


class TestRedactRelpath(unittest.TestCase):
    def test_dirs_and_basename(self):
        # 'asmith' dir → renamed; 'projectzeta' (plain) basename → left as-is (flagged).
        new, hits = FilenameRedactor(MAP).redact_relpath("asmith/sub/projectzeta_plan.md")
        self.assertEqual(str(new), "PERSON_A/sub/projectzeta_plan.md")
        self.assertEqual(hits, 1)

    def test_clean_relpath_unchanged(self):
        new, hits = FilenameRedactor(MAP).redact_relpath("docs/readme.md")
        self.assertEqual(str(new), "docs/readme.md")
        self.assertEqual(hits, 0)


class TestResolveCollisions(unittest.TestCase):
    def test_collision_gets_deterministic_suffix(self):
        items = [
            ("a/asmith.md", "out/PERSON_A.md"),
            ("b/asmith.md", "out/PERSON_A.md"),
            ("c/asmith.md", "out/PERSON_A.md"),
        ]
        result = dict(resolve_collisions(items))
        self.assertEqual(result["a/asmith.md"], "out/PERSON_A.md")
        self.assertEqual(result["b/asmith.md"], "out/PERSON_A__2.md")
        self.assertEqual(result["c/asmith.md"], "out/PERSON_A__3.md")

    def test_no_collision_unchanged(self):
        items = [("a.md", "A.md"), ("b.md", "B.md")]
        self.assertEqual(dict(resolve_collisions(items)), {"a.md": "A.md", "b.md": "B.md"})

    def test_suffix_inserted_before_extension(self):
        items = [("x.png", "R.png"), ("y.png", "R.png")]
        self.assertEqual(dict(resolve_collisions(items))["y.png"], "R__2.png")


class TestPlanTree(unittest.TestCase):
    def test_plan_maps_and_counts(self):
        plan, stats = plan_tree(
            ["asmith_notes.md", "asmith/projectzeta.md", "clean/x.md"],
            FilenameRedactor(MAP),
        )
        self.assertEqual(plan["asmith_notes.md"], "PERSON_A_notes.md")
        self.assertEqual(plan["asmith/projectzeta.md"], "PERSON_A/projectzeta.md")
        self.assertEqual(plan["clean/x.md"], "clean/x.md")
        self.assertEqual(stats["files_renamed"], 1)   # asmith_notes.md basename
        self.assertEqual(stats["dirs_renamed"], 1)     # 'asmith' dir
        self.assertEqual(stats["flagged_files"], 1)    # projectzeta survives in output name
        self.assertEqual(stats["collisions"], 0)

    def test_plan_resolves_collisions(self):
        r = FilenameRedactor([{"find": "asmith", "replace": "[P]"}])
        plan, stats = plan_tree(["d/Asmith.md", "d/asmith.md"], r)
        self.assertEqual(sorted(plan.values()), ["d/P.md", "d/P__2.md"])
        self.assertEqual(stats["collisions"], 1)

    def test_plan_surfaces_skipped_short(self):
        r = FilenameRedactor([{"find": "ed", "replace": "[E]"}], min_len=4)
        _plan, stats = plan_tree(["edited.md"], r)
        self.assertEqual(stats["skipped_short"], ["ed"])


class TestSummarize(unittest.TestCase):
    def test_summarize_subset_of_plan(self):
        r = FilenameRedactor(MAP)
        full = ["asmith_notes.md", "asmith/projectzeta.md", "clean/x.md"]
        plan, _ = plan_tree(full, r)
        stats = summarize(["asmith/projectzeta.md"], plan, r)
        self.assertEqual(stats["files_renamed"], 0)    # basename not renamed (plain)
        self.assertEqual(stats["dirs_renamed"], 1)     # its 'asmith' dir changed
        self.assertEqual(stats["flagged_files"], 1)    # projectzeta still in the name
        self.assertEqual(stats["collisions"], 0)

    def test_summarize_counts_collision_suffix(self):
        r = FilenameRedactor([{"find": "asmith", "replace": "[P]"}])
        full = ["d/Asmith.md", "d/asmith.md"]
        plan, _ = plan_tree(full, r)
        self.assertEqual(summarize(full, plan, r)["collisions"], 1)


class TestCollectFlags(unittest.TestCase):
    def test_collect_pairs_output_name_and_terms(self):
        r = FilenameRedactor(MAP)
        plan, _ = plan_tree(["asmith/projectzeta.md", "clean/x.md"], r)
        flags = collect_filename_flags(["asmith/projectzeta.md", "clean/x.md"], plan, r)
        self.assertEqual(flags, [("PERSON_A/projectzeta.md", ["projectzeta"])])

    def test_render_flags_file_lists_output_name(self):
        out = render_flags_file([("PERSON_A/projectzeta.md", ["projectzeta"])])
        self.assertIn("PERSON_A/projectzeta.md", out)
        self.assertIn("projectzeta", out)


class TestRenderRenameMap(unittest.TestCase):
    def test_contains_old_and_new(self):
        out = render_rename_map([("asmith_1on1.png", "PERSON_A_1on1.png")])
        self.assertIn("asmith_1on1.png", out)
        self.assertIn("PERSON_A_1on1.png", out)

    def test_empty_when_no_renames(self):
        out = render_rename_map([])
        self.assertNotIn("asmith", out)


class TestFilenameReportSection(unittest.TestCase):
    """The FILENAME REDACTIONS report subsection — counts only, never old filenames."""

    def _empty_report(self):
        from report_format import build_redaction_report
        return build_redaction_report({}, [])

    def test_section_renders_counts_including_flags(self):
        from report_format import render_redaction_report
        out = render_redaction_report(
            self._empty_report(), title="X", files_scanned=3, files_matched=1,
            filename_stats={"files_renamed": 2, "dirs_renamed": 1, "collisions": 0,
                            "flagged_files": 1, "skipped_short": ["ed"]})
        self.assertIn("FILENAME REDACTIONS", out)
        self.assertIn("Files renamed", out)
        self.assertIn("Plain-keyword leaks", out)

    def test_section_never_contains_old_filenames(self):
        from report_format import render_redaction_report
        out = render_redaction_report(
            self._empty_report(), title="X", files_scanned=1, files_matched=1,
            filename_stats={"files_renamed": 1, "dirs_renamed": 0, "collisions": 0,
                            "flagged_files": 0, "skipped_short": []})
        self.assertNotIn("asmith", out)

    def test_section_absent_when_feature_off(self):
        from report_format import render_redaction_report
        out = render_redaction_report(self._empty_report(), title="X",
                                      files_scanned=1, files_matched=0)
        self.assertNotIn("FILENAME REDACTIONS", out)


if __name__ == "__main__":
    unittest.main()
