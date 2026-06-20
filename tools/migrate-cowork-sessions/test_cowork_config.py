import os
import tempfile
import unittest
from pathlib import Path

import cowork_config as cc


class LoadDotenv(unittest.TestCase):
    def _write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / ".env"
        p.write_text(text, encoding="utf-8")
        return p

    def test_parses_key_value_skips_comments_blanks_and_strips_quotes(self):
        p = self._write(
            "# a comment\n"
            "\n"
            "COWORK_WORKSPACE=aaa/bbb\n"
            '  COWORK_SPACE = "demo-space" \n'
            "COWORK_TARGET='/tmp/x'\n"
            "NO_EQUALS_LINE\n"
        )
        d = cc.load_dotenv(p)
        self.assertEqual(d["COWORK_WORKSPACE"], "aaa/bbb")
        self.assertEqual(d["COWORK_SPACE"], "demo-space")
        self.assertEqual(d["COWORK_TARGET"], "/tmp/x")
        self.assertNotIn("NO_EQUALS_LINE", d)

    def test_missing_file_returns_empty(self):
        self.assertEqual(cc.load_dotenv(Path("/tmp/does-not-exist-xyz/.env")), {})


class Resolve(unittest.TestCase):
    def setUp(self):
        os.environ.pop("COWORK_SPACE", None)

    def tearDown(self):
        os.environ.pop("COWORK_SPACE", None)

    def test_precedence_flag_over_env_over_dotenv(self):
        os.environ["COWORK_SPACE"] = "from-env"
        self.assertEqual(cc.resolve("from-flag", "COWORK_SPACE", {"COWORK_SPACE": "from-dotenv"}), "from-flag")

    def test_env_beats_dotenv_when_no_flag(self):
        os.environ["COWORK_SPACE"] = "from-env"
        self.assertEqual(cc.resolve(None, "COWORK_SPACE", {"COWORK_SPACE": "from-dotenv"}), "from-env")

    def test_dotenv_when_no_flag_no_env(self):
        self.assertEqual(cc.resolve(None, "COWORK_SPACE", {"COWORK_SPACE": "from-dotenv"}), "from-dotenv")

    def test_none_when_nothing_set(self):
        self.assertIsNone(cc.resolve(None, "COWORK_SPACE", {}))


class ResolveWorkspace(unittest.TestCase):
    def test_relative_joins_base(self):
        base = Path("/base")
        self.assertEqual(cc.resolve_workspace("aaa/bbb", {}, base=base), Path("/base/aaa/bbb"))

    def test_absolute_used_as_is(self):
        base = Path("/base")
        self.assertEqual(cc.resolve_workspace("/abs/ws", {}, base=base), Path("/abs/ws"))

    def test_missing_returns_none(self):
        self.assertIsNone(cc.resolve_workspace(None, {}, base=Path("/base")))


if __name__ == "__main__":
    unittest.main()
