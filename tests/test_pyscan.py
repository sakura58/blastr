import unittest

from blastr import pyscan

SOURCE = '''\
"""demo module."""
from os import path as osp

LIMIT = 3

__all__ = ["outer"]


def outer(a, b=1, *args, c, **kw):
    return inner(a)


def inner(x):
    return x


class User:
    def __init__(self, name):
        self.name = name

    async def fetch(self):
        return await load(self.name)
'''


class PyScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = pyscan.scan("demo.py", SOURCE)

    def test_parses(self):
        self.assertTrue(self.mod.ok, self.mod.error)

    def test_symbols(self):
        names = set(self.mod.symbols)
        self.assertEqual(
            names,
            {"outer", "inner", "User", "User.__init__", "User.fetch", "LIMIT"},
        )

    def test_signature_is_normalised(self):
        self.assertEqual(self.mod.symbols["outer"].signature, "outer(a, b=1, *args, c, **kw)")

    def test_kinds_and_async(self):
        self.assertEqual(self.mod.symbols["User"].kind, "class")
        self.assertEqual(self.mod.symbols["User.fetch"].kind, "method")
        self.assertTrue(self.mod.symbols["User.fetch"].is_async)
        self.assertEqual(self.mod.symbols["LIMIT"].kind, "constant")

    def test_imports_are_recorded(self):
        self.assertEqual(self.mod.imports["osp"], ("os", "path"))

    def test_call_sites_have_the_enclosing_function(self):
        calls = {(call.callee, call.caller) for call in self.mod.calls}
        self.assertIn(("inner", "outer"), calls)
        self.assertIn(("load", "User.fetch"), calls)

    def test_body_hash_ignores_whitespace_but_not_logic(self):
        same = SOURCE.replace("return inner(a)", "return inner(a)  # note")
        other = SOURCE.replace("return inner(a)", "return inner(b)")
        base = pyscan.scan("demo.py", SOURCE).symbols["outer"]
        self.assertEqual(base.body_hash, pyscan.scan("demo.py", same).symbols["outer"].body_hash)
        self.assertNotEqual(base.body_hash, pyscan.scan("demo.py", other).symbols["outer"].body_hash)

    def test_syntax_error_is_reported_not_raised(self):
        mod = pyscan.scan("broken.py", "def oops(:\n")
        self.assertFalse(mod.ok)
        self.assertIn("syntax error", mod.error)


if __name__ == "__main__":
    unittest.main()
