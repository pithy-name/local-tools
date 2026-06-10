"""The benign-Presidio-warning filter drops expected noise but keeps real warnings.

Presidio emits two kinds of WARNING noise that are expected for an English-only
setup and should not reach the user:
  1. "<TYPE> is not mapped to a Presidio entity" — spaCy types Presidio can't map.
  2. "Recognizer not added to registry because language is not supported …" —
     locale-specific predefined recognizers (Spanish CreditCard, passport, etc.)
     skipped because the registry is en-only.

    .venv/bin/python -m unittest tests.test_log_filter -v
Stdlib-only — does NOT load Presidio/spaCy, so it also runs under system python3.
"""
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _record(msg):
    return logging.LogRecord("presidio-analyzer", logging.WARNING,
                             __file__, 0, msg, args=None, exc_info=None)


class TestBenignPresidioFilter(unittest.TestCase):
    def setUp(self):
        self.f = redact._BenignPresidioFilter()

    def test_drops_not_mapped(self):
        self.assertFalse(self.f.filter(_record(
            "DATE_TIME is not mapped to a Presidio entity, but Presidio can still use it")))

    def test_drops_unsupported_language_creditcard(self):
        self.assertFalse(self.f.filter(_record(
            "Recognizer not added to registry because language is not supported by "
            "registry - CreditCardRecognizer supported languages: es, registry "
            "supported languages: en")))

    def test_drops_unsupported_language_any_recognizer(self):
        # Same message, different recognizer (passport, etc.) → still dropped.
        self.assertFalse(self.f.filter(_record(
            "Recognizer not added to registry because language is not supported by "
            "registry - EsNifRecognizer supported languages: es, registry "
            "supported languages: en")))

    def test_keeps_real_warning(self):
        self.assertTrue(self.f.filter(_record(
            "Something genuinely wrong happened during analysis")))


class TestSilenceInstaller(unittest.TestCase):
    def test_installs_filter_once_idempotent(self):
        # Calling repeatedly must not stack duplicate filters on the logger.
        redact._silence_benign_presidio_warnings()
        redact._silence_benign_presidio_warnings()
        lg = logging.getLogger("presidio-analyzer")
        n = sum(isinstance(f, redact._BenignPresidioFilter) for f in lg.filters)
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
