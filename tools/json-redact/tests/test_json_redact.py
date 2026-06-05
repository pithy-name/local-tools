import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import json_redact as jr


def write(tmp: Path, name: str, obj) -> Path:
    p = tmp / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


class TestLoadMappings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_valid_list_loads(self):
        p = write(self.tmp, "m.json",
                  [{"find": "Alice Chen", "replace": "[PERSON_A]"}])
        out = jr.load_mappings(p)
        self.assertEqual(out, [{"find": "Alice Chen", "replace": "[PERSON_A]"}])

    def test_not_a_list_exits(self):
        p = write(self.tmp, "m.json", {"find": "x", "replace": "y"})
        with self.assertRaises(SystemExit):
            jr.load_mappings(p)

    def test_empty_find_exits(self):
        p = write(self.tmp, "m.json", [{"find": "", "replace": "[X]"}])
        with self.assertRaises(SystemExit):
            jr.load_mappings(p)

    def test_missing_replace_exits(self):
        p = write(self.tmp, "m.json", [{"find": "Bob"}])
        with self.assertRaises(SystemExit):
            jr.load_mappings(p)

    def test_duplicate_find_case_insensitive_exits(self):
        p = write(self.tmp, "m.json",
                  [{"find": "Bob", "replace": "[A]"},
                   {"find": "bob", "replace": "[B]"}])
        with self.assertRaises(SystemExit):
            jr.load_mappings(p)

    def test_shared_replace_exits(self):
        p = write(self.tmp, "m.json",
                  [{"find": "Alice", "replace": "[P]"},
                   {"find": "Bob", "replace": "[P]"}])
        with self.assertRaises(SystemExit):
            jr.load_mappings(p)


class TestRedactString(unittest.TestCase):
    def _redactor(self, mappings):
        pattern, lookup = jr.build_pattern(mappings)
        counts = Counter()
        return jr.make_redactor(pattern, lookup, counts), counts

    def test_basic_swap(self):
        rd, _ = self._redactor([{"find": "Alice Chen", "replace": "[PERSON_A]"}])
        self.assertEqual(rd("met Alice Chen today"), "met [PERSON_A] today")

    def test_case_insensitive(self):
        rd, _ = self._redactor([{"find": "Bob", "replace": "[B]"}])
        self.assertEqual(rd("BOB and bob"), "[B] and [B]")

    def test_word_boundary(self):
        rd, _ = self._redactor([{"find": "Bob", "replace": "[B]"}])
        self.assertEqual(rd("bobbin"), "bobbin")  # no boundary → untouched

    def test_longest_first(self):
        rd, _ = self._redactor([
            {"find": "Alice", "replace": "[FIRST]"},
            {"find": "Alice Chen", "replace": "[FULL]"},
        ])
        self.assertEqual(rd("Alice Chen and Alice"), "[FULL] and [FIRST]")

    def test_replacement_not_rematched(self):
        # 'Chen' must NOT eat the output of the 'Alice Chen' swap
        rd, _ = self._redactor([
            {"find": "Alice Chen", "replace": "[PERSON_A]"},
            {"find": "Chen", "replace": "[SURNAME]"},
        ])
        self.assertEqual(rd("Alice Chen"), "[PERSON_A]")

    def test_counts(self):
        rd, counts = self._redactor([{"find": "Bob", "replace": "[B]"}])
        rd("Bob saw Bob")
        self.assertEqual(counts["Bob"], 2)

    def test_empty_mappings_noop(self):
        rd, _ = self._redactor([])
        self.assertEqual(rd("anything"), "anything")


class TestWalk(unittest.TestCase):
    def _rd(self, mappings):
        pattern, lookup = jr.build_pattern(mappings)
        return jr.make_redactor(pattern, lookup, Counter())

    def test_values_swapped_keys_untouched(self):
        rd = self._rd([{"find": "Alice", "replace": "[A]"}])
        obj = {"Alice": "Alice met Bob", "author": "Alice"}
        self.assertEqual(jr.walk(obj, rd),
                         {"Alice": "[A] met Bob", "author": "[A]"})

    def test_nested_and_arrays(self):
        rd = self._rd([{"find": "Bob", "replace": "[B]"}])
        obj = {"notes": [{"body": "Bob"}, {"body": "no name"}]}
        self.assertEqual(jr.walk(obj, rd),
                         {"notes": [{"body": "[B]"}, {"body": "no name"}]})

    def test_non_strings_preserved(self):
        rd = self._rd([{"find": "Bob", "replace": "[B]"}])
        obj = {"n": 42, "f": 3.5, "b": True, "z": None, "s": "Bob"}
        self.assertEqual(jr.walk(obj, rd),
                         {"n": 42, "f": 3.5, "b": True, "z": None, "s": "[B]"})


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.mappings = self.tmp / "mappings.json"
        self.mappings.write_text(
            json.dumps([{"find": "Alice Chen", "replace": "[PERSON_A]"}]),
            encoding="utf-8")

    def _make(self, rel, obj):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def test_writes_valid_redacted_json(self):
        self._make("note.json", {"body": "Alice Chen spoke"})
        stats = jr.run(self.tmp, self.mappings, dry_run=False)
        out = self.tmp / "redacted" / "note.json"
        self.assertTrue(out.exists())
        loaded = json.loads(out.read_text(encoding="utf-8"))  # valid JSON
        self.assertEqual(loaded, {"body": "[PERSON_A] spoke"})
        self.assertEqual(stats["processed"], 1)

    def test_original_untouched(self):
        src = self._make("note.json", {"body": "Alice Chen"})
        jr.run(self.tmp, self.mappings, dry_run=False)
        self.assertEqual(json.loads(src.read_text()), {"body": "Alice Chen"})

    def test_dry_run_writes_nothing(self):
        self._make("note.json", {"body": "Alice Chen"})
        jr.run(self.tmp, self.mappings, dry_run=True)
        self.assertFalse((self.tmp / "redacted").exists())

    def test_non_json_not_copied_but_reported(self):
        self._make("note.json", {"body": "hi"})
        (self.tmp / "secret.pdf").write_bytes(b"%PDF-1.4 unredacted")
        stats = jr.run(self.tmp, self.mappings, dry_run=False)
        self.assertFalse((self.tmp / "redacted" / "secret.pdf").exists())
        self.assertEqual(stats["non_json"], 1)

    def test_malformed_json_errors_not_copied(self):
        bad = self.tmp / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        stats = jr.run(self.tmp, self.mappings, dry_run=False)
        self.assertFalse((self.tmp / "redacted" / "bad.json").exists())
        self.assertEqual(stats["errors"], 1)

    def test_redacted_subtree_excluded_from_walk(self):
        self._make("note.json", {"body": "Alice Chen"})
        jr.run(self.tmp, self.mappings, dry_run=False)
        stats = jr.run(self.tmp, self.mappings, dry_run=False)  # 2nd run
        self.assertEqual(stats["processed"], 1)  # not 2 — output not re-walked

    def test_idempotent(self):
        self._make("note.json", {"body": "Alice Chen"})
        jr.run(self.tmp, self.mappings, dry_run=False)
        out = self.tmp / "redacted" / "note.json"
        first = out.read_text()
        jr.run(self.tmp, self.mappings, dry_run=False)
        self.assertEqual(out.read_text(), first)


if __name__ == "__main__":
    unittest.main()
