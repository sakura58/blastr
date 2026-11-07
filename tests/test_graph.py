import shutil
import unittest

from blastr import diffparse
from blastr.graph import analyze
from support import AFTER, BEFORE, make_patch, make_repo


class GraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = make_repo(AFTER)
        cls.patch = make_patch(BEFORE, AFTER)
        cls.result = analyze(cls.root, diffparse.parse(cls.patch), dict(BEFORE), depth=2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_changed_symbols(self):
        names = {change.symbol.qualname for change in self.result.changes}
        self.assertIn("create_user", names)
        self.assertIn("User.to_dict", names)
        self.assertIn("User.__init__", names)

    def test_call_site_in_untouched_file_is_found(self):
        hits = [occ for occ in self.result.occurrences if occ.file == "api/admin.py"]
        self.assertTrue(hits, "the call site living in api/admin.py must be in the blast radius")
        self.assertTrue(any(occ.callee == "create_user" for occ in hits))

    def test_signature_break_is_high_with_evidence(self):
        risks = [risk for risk in self.result.risks if risk.id == "R002" and risk.symbol == "create_user"]
        self.assertTrue(risks)
        self.assertEqual(risks[0].level, "high")
        self.assertIn("api/admin.py", risks[0].file)
        self.assertIn("create_user", risks[0].evidence)

    def test_new_serialized_key_is_reported(self):
        titles = [risk.title for risk in self.result.risks if risk.id == "R004"]
        self.assertTrue(any("role" in title for title in titles), titles)

    def test_exact_assertion_is_detected(self):
        self.assertTrue([risk for risk in self.result.risks if risk.id == "R009"])

    def test_before_image_is_required_for_signature_detection(self):
        without_history = analyze(self.root, diffparse.parse(self.patch), {}, depth=1)
        kinds = {change.kind for change in without_history.changes}
        self.assertIn("touched", kinds)
        self.assertNotIn("signature", kinds)

    def test_verdict(self):
        self.assertEqual(self.result.level, "high")
        self.assertGreaterEqual(self.result.stats["call_sites"], 2)


if __name__ == "__main__":
    unittest.main()
