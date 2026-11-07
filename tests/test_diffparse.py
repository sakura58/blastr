import unittest

from blastr import diffparse

OLD = 'def hello():\n    return "hi"\n\n\ndef bye():\n    pass\n'
NEW = 'def hello():\n    return "hello"\n\n\ndef bye():\n    pass\n'

GIT_PATCH = '''\
diff --git a/app.py b/app.py
index 0a1b2c3..4d5e6f7 100644
--- a/app.py
+++ b/app.py
@@ -1,6 +1,6 @@
 def hello():
-    return "hi"
+    return "hello"
 
 
 def bye():
     pass
'''

PLAIN_PATCH = """\
--- a/a.txt
+++ b/a.txt
@@ -1,1 +1,1 @@
-one
+ONE
--- a/b.txt
+++ b/b.txt
@@ -1,1 +1,1 @@
-two
+TWO
"""

NEW_FILE_PATCH = """\
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
"""


class DiffParseTest(unittest.TestCase):
    def test_git_header_and_hunk_numbers(self):
        diffs = diffparse.parse(GIT_PATCH)
        self.assertEqual(len(diffs), 1)
        fd = diffs[0]
        self.assertEqual(fd.path, "app.py")
        self.assertEqual(fd.added, [(2, '    return "hello"')])
        self.assertEqual(fd.removed, [(2, '    return "hi"')])
        self.assertEqual(fd.new_ranges(), [(2, 2)])
        self.assertEqual(fd.additions, 1)
        self.assertEqual(fd.deletions, 1)

    def test_reverse_apply_rebuilds_the_before_image(self):
        fd = diffparse.parse(GIT_PATCH)[0]
        self.assertEqual(diffparse.reverse_apply(NEW, fd), OLD)

    def test_reverse_apply_refuses_stale_patch(self):
        fd = diffparse.parse(GIT_PATCH)[0]
        self.assertIsNone(diffparse.reverse_apply("totally different\nfile\n", fd))

    def test_plain_unified_diff_with_two_files(self):
        diffs = diffparse.parse(PLAIN_PATCH)
        self.assertEqual([d.path for d in diffs], ["a.txt", "b.txt"])
        self.assertEqual([d.added for d in diffs], [[(1, "ONE")], [(1, "TWO")]])

    def test_new_file(self):
        fd = diffparse.parse(NEW_FILE_PATCH)[0]
        self.assertTrue(fd.is_new)
        self.assertEqual(fd.path, "new.py")
        self.assertEqual([text for _, text in fd.added], ["x = 1", "y = 2"])

    def test_binary_is_flagged(self):
        patch = "diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n"
        fd = diffparse.parse(patch)[0]
        self.assertTrue(fd.is_binary)

    def test_empty_input(self):
        self.assertEqual(diffparse.parse(""), [])


if __name__ == "__main__":
    unittest.main()
