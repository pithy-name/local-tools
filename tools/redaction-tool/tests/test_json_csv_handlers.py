"""Tests for redact.py's JSON/CSV handlers (parse-aware, values-only).

Run under the venv (importing redact.py needs yaml/presidio):
    .venv/bin/python -m unittest tests.test_json_csv_handlers -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _kw_cfg(mappings):
    cfg = dict(redact.DEFAULT_CONFIG)
    cfg["entities"] = []
    cfg["custom_keywords"] = mappings
    return cfg


class TestProcessJson(unittest.TestCase):
    def test_redacts_string_values_only_keeps_valid_json(self):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "n.json"
        src.write_text(json.dumps({
            "author": "Mary Bello",
            "Mary Bello": "x",          # a key that matches — must stay (keys untouched)
            "n": 5,                      # non-string — untouched
            "body": "hi Mary Bello",
        }), encoding="utf-8")
        cfg = _kw_cfg([{"find": "Mary Bello", "replace": "[PERSON_A]"}])
        kr = redact.make_keyword_redactor_from_config(cfg)
        dst = tmp / "out.json"
        n = redact.process_json(src, dst, None, cfg, {}, dry_run=False, kr=kr)
        out = json.loads(dst.read_text(encoding="utf-8"))  # valid JSON
        self.assertEqual(out, {
            "author": "[PERSON_A]",
            "Mary Bello": "x",
            "n": 5,
            "body": "hi [PERSON_A]",
        })
        self.assertEqual(n, 2)


class TestProcessCsv(unittest.TestCase):
    def test_redacts_every_cell_keeps_valid_csv(self):
        import csv
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "n.csv"
        src.write_text("name,note\nMary Bello,met Mary Bello\nBob,ok\n", encoding="utf-8")
        cfg = _kw_cfg([{"find": "Mary Bello", "replace": "[PERSON_A]"}])
        kr = redact.make_keyword_redactor_from_config(cfg)
        dst = tmp / "out.csv"
        n = redact.process_csv(src, dst, None, cfg, {}, dry_run=False, kr=kr)
        with dst.open(encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows, [["name", "note"],
                                ["[PERSON_A]", "met [PERSON_A]"],
                                ["Bob", "ok"]])
        self.assertEqual(n, 2)


class TestJsonEndToEnd(unittest.TestCase):
    def test_keyword_run_redacts_json_without_loading_model(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "note.json").write_text(json.dumps({"body": "Mary Bello"}), encoding="utf-8")
        cfg = _kw_cfg([{"find": "Mary Bello", "replace": "[PERSON_A]"}])
        with mock.patch.object(redact, "build_analyzer",
                               side_effect=AssertionError("model loaded for a JSON-only keyword run")):
            redact.run(tmp, cfg, dry_run=False)
        out = json.loads((tmp / "redacted" / "note.json").read_text(encoding="utf-8"))
        self.assertEqual(out, {"body": "[PERSON_A]"})


class TestRunLevelCoverage(unittest.TestCase):
    def test_csv_redacted_via_run_dispatch(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "t.csv").write_text("name\nMary Bello\n", encoding="utf-8")
        cfg = _kw_cfg([{"find": "Mary Bello", "replace": "[PERSON_A]"}])
        redact.run(tmp, cfg, dry_run=False)
        out = (tmp / "redacted" / "t.csv").read_text(encoding="utf-8")
        self.assertIn("[PERSON_A]", out)
        self.assertNotIn("Mary Bello", out)

    def test_per_pseudonym_report_emitted_by_run(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "n.md").write_text("Mary Bello and Mary Bello", encoding="utf-8")
        cfg = _kw_cfg([{"find": "Mary Bello", "replace": "[PERSON_A]"}])
        with self.assertLogs("redact", level="INFO") as cm:
            redact.run(tmp, cfg, dry_run=False)
        log = "\n".join(cm.output)
        self.assertIn("[PERSON_A]", log)
        self.assertIn("text-sub: 2", log)
        self.assertIn("blackout: N/A", log)


class TestLeakGuard(unittest.TestCase):
    def _dir_with_unhandled(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "note.md").write_text("hi", encoding="utf-8")
        (tmp / "data.zip").write_bytes(b"PK fake-zip")
        return tmp

    def test_unhandled_not_copied_by_default(self):
        tmp = self._dir_with_unhandled()
        cfg = _kw_cfg([])  # keyword-only, no model needed
        redact.run(tmp, cfg, dry_run=False)
        self.assertFalse((tmp / "redacted" / "data.zip").exists())

    def test_unhandled_copied_when_opted_in(self):
        tmp = self._dir_with_unhandled()
        cfg = _kw_cfg([])
        cfg["copy_unhandled"] = True
        redact.run(tmp, cfg, dry_run=False)
        self.assertTrue((tmp / "redacted" / "data.zip").exists())

    def test_unhandled_paths_listed_in_summary(self):
        tmp = self._dir_with_unhandled()  # note.md + data.zip
        cfg = _kw_cfg([])
        with self.assertLogs("redact", level="INFO") as cm:
            redact.run(tmp, cfg, dry_run=False)
        log = "\n".join(cm.output)
        self.assertIn("not copied: data.zip", log)  # the path, not just the count


if __name__ == "__main__":
    unittest.main()
