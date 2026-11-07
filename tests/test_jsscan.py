import unittest

from blastr import jsscan

SOURCE = """\
import { fetchUser } from './api';
const fs = require('fs');

export function renderUser(user) {
  return fetchUser(user.id);
}

export const load = async (url) => {
  return fetch(url);
};

class Store {
  get(key) {
    return this.data[key];
  }
}
"""


class JsScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = jsscan.scan("app.ts", SOURCE)

    def test_function_and_class_symbols(self):
        names = set(self.mod.symbols)
        self.assertIn("renderUser", names)
        self.assertIn("load", names)
        self.assertIn("Store", names)
        self.assertIn("Store.get", names)

    def test_imports(self):
        self.assertIn("fetchUser", self.mod.imports)
        self.assertEqual(self.mod.imports["fetchUser"], ("./api", "fetchUser"))
        self.assertIn("fs", self.mod.imports)

    def test_call_sites(self):
        callees = {call.callee for call in self.mod.calls}
        self.assertIn("fetchUser", callees)
        self.assertIn("fetch", callees)

    def test_definitions_are_not_counted_as_calls(self):
        pairs = [(call.lineno, call.callee) for call in self.mod.calls]
        self.assertNotIn((4, "renderUser"), pairs)
        self.assertNotIn((13, "get"), pairs)


if __name__ == "__main__":
    unittest.main()
