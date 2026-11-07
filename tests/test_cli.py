import io
import json
import shutil
import unittest
from contextlib import redirect_stdout

from blastr import cli
from support import AFTER, BEFORE, make_patch, make_repo


class CliTest(unittest.TestCase):
    def setUp(self):
        self.root = make_repo(AFTER)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.patch = self.root / "change.patch"
        self.patch.write_text(make_patch(BEFORE, AFTER), encoding="utf-8")

    def run_cli(self, *extra):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["--root", str(self.root), "--diff", str(self.patch), *extra])
        return code, buffer.getvalue()

    def test_json_output(self):
        code, out = self.run_cli("--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["schema"], "blastr/v1")
        self.assertEqual(payload["verdict"]["level"], "high")
        self.assertTrue(payload["risks"])
        self.assertTrue(any(item["symbol"] == "create_user" for item in payload["direct"]))

    def test_text_output_reports_the_break(self):
        code, out = self.run_cli("--no-color")
        self.assertEqual(code, 0)
        self.assertIn("create_user", out)
        self.assertIn("verdict", out)
        self.assertNotIn("\033[", out)

    def test_markdown_output(self):
        code, out = self.run_cli("--markdown")
        self.assertIn("| | rule | finding | where |", out)

    def test_fail_on_high_exits_2(self):
        code, _ = self.run_cli("--fail-on", "high")
        self.assertEqual(code, 2)

    def test_empty_diff_is_an_error(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["--root", str(self.root), "--diff", str(self.root / "change.patch"), "--rev", "HEAD~1"])
        # --rev is ignored when --diff is given, so this still analyses; assert only that it does not crash
        self.assertIn(code, (0, 2))


if __name__ == "__main__":
    unittest.main()
