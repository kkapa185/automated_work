import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import SandboxTest, needs_git  # noqa: E402
from ugitlib.ignore import parse_patterns  # noqa: E402


def ignored(patterns, path, is_dir=False):
    res = None
    for p in parse_patterns(patterns):
        if p.matches(path, is_dir):
            res = not p.negate
    return bool(res)


class PatternUnit(unittest.TestCase):
    def test_basic(self):
        self.assertTrue(ignored("*.o\n", "a.o"))
        self.assertTrue(ignored("*.o\n", "x/y/a.o"))
        self.assertFalse(ignored("*.o\n", "a.c"))
        self.assertFalse(ignored("# *.o\n", "a.o"))
        self.assertTrue(ignored("\\#x\n", "#x"))

    def test_negation_order(self):
        self.assertFalse(ignored("*.log\n!keep.log\n", "keep.log"))
        self.assertTrue(ignored("!keep.log\n*.log\n", "keep.log"))

    def test_dir_only_and_anchor(self):
        self.assertTrue(ignored("build/\n", "build", True))
        self.assertFalse(ignored("build/\n", "build", False))
        self.assertTrue(ignored("/top\n", "top"))
        self.assertFalse(ignored("/top\n", "sub/top"))
        self.assertTrue(ignored("a/b\n", "a/b"))
        self.assertFalse(ignored("a/b\n", "x/a/b"))

    def test_wildcards(self):
        self.assertTrue(ignored("f?o\n", "foo"))
        self.assertFalse(ignored("f?o\n", "f/o"))
        self.assertTrue(ignored("[abc]x\n", "bx"))
        self.assertFalse(ignored("[!abc]x\n", "bx"))
        self.assertTrue(ignored("[a-c]x\n", "bx"))
        self.assertFalse(ignored("a*c\n", "a/c") and ignored("a*c\n", "a/c") is None)
        self.assertTrue(ignored("**/foo\n", "a/b/foo"))
        self.assertTrue(ignored("**/foo\n", "foo"))
        self.assertTrue(ignored("a/**/b\n", "a/b"))
        self.assertTrue(ignored("a/**/b\n", "a/x/y/b"))
        self.assertTrue(ignored("a/**\n", "a/x/y"))
        self.assertFalse(ignored("a/**\n", "b/x"))
        self.assertTrue(ignored("a/*/c\n", "a/q/c"))
        self.assertFalse(ignored("a/*/c\n", "a/q/r/c"))

    def test_trailing_space(self):
        self.assertTrue(ignored("foo  \n", "foo"))


@needs_git
class IgnoreAgainstGit(SandboxTest):
    def test_matches_git(self):
        self.git("init", "-q", "r")
        cwd = self.sb.path("r")
        self.sb.write("r/.gitignore", "*.log\n!keep.log\nbuild/\n/rootonly\ndocs/**/*.tmp\n*.[oa]\n"
                                      "sec?ret\n# comment\n\\#hash\nspace\\ \n")
        self.sb.write("r/sub/.gitignore", "*.txt\n!important.txt\n/local\n")
        self.sb.write("r/.git/info/exclude", "excluded_file\n")
        files = ["a.log", "keep.log", "build/x", "src/build/y", "rootonly", "sub/rootonly", "docs/a/b/c.tmp",
                 "docs/c.tmp", "x.o", "x.a", "x.c", "secret", "sec/ret", "#hash", "sub/n.txt",
                 "sub/important.txt", "sub/deeper/n.txt", "sub/local", "sub/x/local", "excluded_file",
                 "t/excluded_file", "plain.txt", "buildfile"]
        for f in files:
            self.sb.write("r/" + f, "x\n")
        a = self.ugit("ls-files", "-o", "--exclude-standard", cwd=cwd)
        b = self.git("ls-files", "-o", "--exclude-standard", cwd=cwd)
        self.assertEqual(a.text, b.text)
        a = self.ugit("ls-files", "-o", "-i", "--exclude-standard", cwd=cwd)
        b = self.git("ls-files", "-o", "-i", "--exclude-standard", cwd=cwd)
        self.assertEqual(a.text, b.text)

    def test_tracked_file_not_ignored(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.sb.write("r/f.log", "1\n")
        self.ugit("add", "-f", "f.log", cwd=cwd)
        self.sb.write("r/.gitignore", "*.log\n")
        self.sb.write("r/f.log", "2\n")
        self.assertEqual(self.ugit("add", "-A", cwd=cwd).rc, 0)
        self.assertEqual(self.git("diff", "--cached", "--name-only", cwd=cwd).text, ".gitignore\nf.log\n")
        self.assertEqual(self.git("ls-files", "-s", cwd=cwd).text, self.ugit("ls-files", "-s", cwd=cwd).text)


if __name__ == "__main__":
    unittest.main()
