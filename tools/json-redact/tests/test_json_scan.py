import json
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import json_scan as js

Span = namedtuple("Span", ["entity_type", "start", "end"])


def fake_analyze(text):
    """Pretend NER: flags the literal 'Alice Chen' as PERSON wherever it appears."""
    spans = []
    needle = "Alice Chen"
    i = text.find(needle)
    while i != -1:
        spans.append(Span("PERSON", i, i + len(needle)))
        i = text.find(needle, i + 1)
    return spans


class TestIterStrings(unittest.TestCase):
    def test_yields_all_string_values_only(self):
        obj = {"k": "a", "n": 5, "list": ["b", {"deep": "c"}], "z": None}
        self.assertEqual(sorted(js.iter_strings(obj)), ["a", "b", "c"])


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _make(self, name, obj):
        (self.tmp / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_collects_and_counts_unique(self):
        self._make("a.json", {"body": "Alice Chen met Alice Chen"})
        self._make("b.json", {"body": "Alice Chen again"})
        found = js.collect(self.tmp, fake_analyze)
        self.assertEqual(found["PERSON"]["Alice Chen"], 3)

    def test_skips_unparseable(self):
        self._make("a.json", {"body": "Alice Chen"})
        (self.tmp / "bad.json").write_text("{nope", encoding="utf-8")
        found = js.collect(self.tmp, fake_analyze)
        self.assertEqual(found["PERSON"]["Alice Chen"], 1)


if __name__ == "__main__":
    unittest.main()
