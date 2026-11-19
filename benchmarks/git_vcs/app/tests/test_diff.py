"""diff: unit tests for the algorithm and differential tests against real git."""
import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import PairTest, needs_git  # noqa: E402
from ugitlib import diff as D  # noqa: E402


def udiff(a, b, ctx=3):
    return b"".join(D.unified_hunks(D.split_lines(a), D.split_lines(b), ctx)).decode()


class AlgorithmKnownAnswers(unittest.TestCase):
    """Expected hunks derived by hand from the unified-diff definition."""

    def test_single_change_with_context(self):
        a = b"1\n2\n3\n4\n5\n6\n7\n8\n9\n"
        b = b"1\n2\n3\n4\nFIVE\n6\n7\n8\n9\n"
        self.assertEqual(udiff(a, b), "@@ -2,7 +2,7 @@\n 2\n 3\n 4\n-5\n+FIVE\n 6\n 7\n 8\n")

    def test_hunks_split_when_far_apart(self):
        a = b"".join(b"%d\n" % i for i in range(1, 21))
        b = a.replace(b"2\n", b"two\n", 1).replace(b"19\n", b"nineteen\n")
        out = udiff(a, b)
        self.assertEqual(out.count("@@ -"), 2)
        self.assertTrue(out.startswith("@@ -1,5 +1,5 @@\n 1\n-2\n+two\n 3\n 4\n 5\n@@ -16,5 +16,5 @@\n"))

    def test_hunks_merge_when_close(self):
        a = b"".join(b"%d\n" % i for i in range(1, 21))
        b = a.replace(b"3\n", b"x\n").replace(b"10\n", b"y\n")  # gap of 6 lines -> merged
        self.assertEqual(udiff(a, b).count("@@ -"), 1)
        b = a.replace(b"3\n", b"x\n").replace(b"11\n", b"y\n")  # gap of 7 lines -> split
        self.assertEqual(udiff(a, b).count("@@ -"), 2)

    def test_no_newline_at_eof(self):
        self.assertEqual(udiff(b"a\nb", b"a\nb\n"), "@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+b\n")
        self.assertEqual(udiff(b"a\nb\n", b"a\nc"),
                         "@@ -1,2 +1,2 @@\n a\n-b\n+c\n\\ No newline at end of file\n")

    def test_new_and_empty_ranges(self):
        self.assertEqual(udiff(b"", b"x\ny\n"), "@@ -0,0 +1,2 @@\n+x\n+y\n")
        self.assertEqual(udiff(b"x\n", b""), "@@ -1 +0,0 @@\n-x\n")

    def test_function_context_in_hunk_header(self):
        a = b"def f():\n    a\n    b\n    c\n    d\n    e\n"
        b = b"def f():\n    a\n    b\n    c\n    d\n    E\n"
        self.assertEqual(udiff(a, b, 1), "@@ -5,2 +5,2 @@ def f():\n     d\n-    e\n+    E\n")

    def test_zero_context(self):
        self.assertEqual(udiff(b"a\nb\nc\n", b"a\nx\nc\n", 0), "@@ -2 +2 @@ a\n-b\n+x\n")

    def test_script_always_valid_and_minimal_on_random_inputs(self):
        rnd = random.Random(7)
        for _ in range(300):
            a = [rnd.choice("abcd").encode() + b"\n" for _ in range(rnd.randint(0, 25))]
            b = [rnd.choice("abcd").encode() + b"\n" for _ in range(rnd.randint(0, 25))]
            c1, c2 = D.diff_changes(a, b)
            self.assertEqual([x for x, c in zip(a, c1) if not c], [x for x, c in zip(b, c2) if not c])
            # LCS length via DP must equal the number of kept lines (minimal edit script)
            n, m = len(a), len(b)
            dp = [[0] * (m + 1) for _ in range(n + 1)]
            for i in range(n):
                for j in range(m):
                    dp[i + 1][j + 1] = dp[i][j] + 1 if a[i] == b[j] else max(dp[i][j + 1], dp[i + 1][j])
            self.assertEqual(len(a) - sum(c1), dp[n][m])

    def test_rename_similarity_and_pretty_names(self):
        self.assertEqual(D.pprint_rename("a/b/c", "a/d/c"), "a/{b => d}/c")
        self.assertEqual(D.pprint_rename("dir/x", "dir2/x"), "{dir => dir2}/x")
        self.assertEqual(D.pprint_rename("a", "b"), "a => b")
        self.assertEqual(D.pprint_rename("a/f", "b/f"), "{a => b}/f")
        self.assertEqual(D.pprint_rename("x/f", "x/g"), "x/{f => g}")
        self.assertEqual(D.similarity(b"same\n", b"same\n"), 60000)
        self.assertEqual(D.similarity(b"a\nb\n", b"c\nd\n"), 0)

    def test_stat_summary_line(self):
        self.assertEqual(D.stat_summary_line(1, 1, 0), " 1 file changed, 1 insertion(+)\n")
        self.assertEqual(D.stat_summary_line(2, 3, 1), " 2 files changed, 3 insertions(+), 1 deletion(-)\n")
        self.assertEqual(D.stat_summary_line(1, 0, 0), " 1 file changed, 0 insertions(+), 0 deletions(-)\n")


class Performance(unittest.TestCase):
    def test_large_mostly_equal_files(self):
        a = [b"line %d\n" % i for i in range(60000)]
        b = list(a)
        for i in range(0, 60000, 997):
            b[i] = b"changed %d\n" % i
        t = time.time()
        D.diff_changes(a, b)
        self.assertLess(time.time() - t, 10)

    def test_completely_different_files(self):
        a = [b"a%d\n" % i for i in range(20000)]
        b = [b"b%d\n" % i for i in range(20000)]
        t = time.time()
        c1, c2 = D.diff_changes(a, b)
        self.assertTrue(all(c1) and all(c2))
        self.assertLess(time.time() - t, 10)

    def test_many_repeated_lines(self):
        rnd = random.Random(3)
        a = [rnd.choice([b"x\n", b"y\n", b"z\n"]) for _ in range(3000)]
        b = [rnd.choice([b"x\n", b"y\n", b"z\n"]) for _ in range(3000)]
        t = time.time()
        c1, c2 = D.diff_changes(a, b)
        self.assertEqual([x for x, c in zip(a, c1) if not c], [x for x, c in zip(b, c2) if not c])
        self.assertLess(time.time() - t, 20)

    def test_single_line_repeated_run(self):
        a = [b"same\n"] * 50000
        b = [b"same\n"] * 49990 + [b"other\n"] * 10
        t = time.time()
        D.diff_changes(a, b)
        self.assertLess(time.time() - t, 10)


@needs_git
class DiffAgainstGit(PairTest):
    def commit_base(self, files):
        for n, c in files.items():
            self.put(n, c)
        self.both("add", ".")
        self.both("commit", "-m", "base")

    def all_forms(self, sub=""):
        for a in (["diff"], ["diff", "--cached"], ["diff", "--staged"], ["diff", "HEAD"], ["diff", "--stat"],
                  ["diff", "--name-only"], ["diff", "--name-status"], ["diff", "--numstat"],
                  ["diff", "--shortstat"], ["diff", "--cached", "--stat"], ["diff", "-U1"],
                  ["diff", "--unified=0"], ["diff", "--summary", "HEAD"], ["diff", "--exit-code"],
                  ["diff", "--quiet"], ["diff", "--cached", "--name-status"], ["diff", "--stat", "--cached"]):
            self.both(*a, sub=sub)

    def test_modify_add_delete(self):
        self.commit_base({"a.txt": "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n", "b.txt": "b\n", "c.txt": "c\n"})
        self.put("a.txt", "1\n2\n3\nfour\n5\n6\n7\n8\n9\n10\n11\n")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "b.txt"))
        self.put("new.txt", "new\n")
        self.both("add", "new.txt")
        self.all_forms()
        self.both("add", "-A")
        self.all_forms()

    def test_no_newline_variants(self):
        self.commit_base({"a": "no newline", "b": "with newline\n", "c": "x\ny"})
        self.put("a", "no newline\n")
        self.put("b", "with newline")
        self.put("c", "x\ny\nz")
        self.all_forms()

    def test_empty_files_and_modes(self):
        self.commit_base({"e": "", "run.sh": "#!/bin/sh\necho\n", "f": "x\n"})
        self.put("e", "now content\n")
        for d in self.dirs.values():
            os.chmod(os.path.join(d, "run.sh"), 0o755)
        self.put("empty_new", "")
        self.both("add", "empty_new")
        self.all_forms()
        self.put("run.sh", "#!/bin/sh\necho changed\n")
        self.all_forms()

    def test_binary(self):
        self.commit_base({"bin": b"\0\1\2\3binary\n", "t": "text\n"})
        self.put("bin", b"\0\1\2\3changed\0")
        self.put("newbin", b"\xff\xfe\0\0")
        self.both("add", "newbin")
        self.all_forms()

    def test_rename_detection(self):
        body = "".join("this is line %d of the document\n" % i for i in range(40))
        self.commit_base({"old.txt": body, "other.txt": "unrelated\n", "keep": "k\n"})
        self.both("mv", "old.txt", "moved/new.txt")
        self.all_forms()
        self.put("moved/new.txt", body.replace("line 3 ", "LINE 3 ").replace("line 30 ", "LINE 30 "))
        self.both("add", "-A")
        self.all_forms()
        self.both("diff", "--cached", "--no-renames")
        self.both("diff", "--cached", "-M")

    def test_exact_copy_rename_with_duplicates(self):
        self.commit_base({"a": "same\ncontent\n", "b": "same\ncontent\n", "z": "other\n"})
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "a"))
            os.unlink(os.path.join(d, "b"))
        self.put("dir/b", "same\ncontent\n")
        self.put("dir/q", "same\ncontent\n")
        self.both("add", "-A")
        self.all_forms()

    def test_type_change(self):
        self.commit_base({"x": "content\n", "t": "target\n"})
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "x"))
            os.symlink("t", os.path.join(d, "x"))
        self.all_forms()
        self.both("add", "x")
        self.all_forms()

    def test_symlink_change(self):
        for d in self.dirs.values():
            os.symlink("target1", os.path.join(d, "ln"))
        self.both("add", ".")
        self.both("commit", "-m", "x")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "ln"))
            os.symlink("target2", os.path.join(d, "ln"))
        self.all_forms()

    def test_commit_vs_commit_and_ranges(self):
        self.commit_base({"a": "1\n2\n3\n", "b": "b\n"})
        self.put("a", "1\n2\n3\n4\n")
        self.both("commit", "-a", "-m", "second")
        self.put("b", "bb\n")
        self.put("c", "c\n")
        self.both("add", ".")
        self.both("commit", "-m", "third")
        for a in (["diff", "HEAD~2", "HEAD"], ["diff", "HEAD~1", "HEAD~2"], ["diff", "HEAD~2..HEAD"],
                  ["diff", "HEAD~1...HEAD"], ["diff", "HEAD~2", "HEAD", "--", "a"],
                  ["diff", "--stat", "HEAD~2", "HEAD"], ["diff", "HEAD~2", "HEAD", "--name-status"],
                  ["diff", "HEAD~1"], ["diff", "HEAD", "HEAD"], ["diff", "master", "master~2"],
                  ["diff", "--cached", "HEAD~1"]):
            self.both(*a)

    def test_pathspec_and_subdir(self):
        self.commit_base({"d/a": "1\n", "d/e/b": "2\n", "top": "t\n"})
        self.put("d/a", "changed\n")
        self.put("d/e/b", "changed\n")
        self.put("top", "changed\n")
        self.both("add", "top")
        for a in (["diff"], ["diff", "--cached"], ["diff", "a"], ["diff", "--", "e"], ["diff", ".."],
                  ["diff", "--name-only"]):
            self.both(*a, sub="d")
        self.both("diff", "--", "d/a")
        self.both("diff", "d")
        self.both("diff", "nonexistent")
        self.both("diff", "--", "nonexistent")

    def test_unborn_and_errors(self):
        self.put("a", "x\n")
        self.both("add", "a")
        self.both("diff", "--cached")
        self.both("diff")
        self.both("diff", "badrev..HEAD")
        self.both("diff", "HEAD")

    def test_weird_names(self):
        self.commit_base({"sp ace.txt": "1\n", "ünï.txt": "2\n", "q\"uote": "3\n"})
        self.put("sp ace.txt", "changed\n")
        self.put("ünï.txt", "changed\n")
        self.put("q\"uote", "changed\n")
        self.all_forms()

    def test_hunk_function_context_and_indent_heuristic(self):
        src = ("def alpha():\n    x = 1\n    return x\n\n\ndef beta():\n    y = 2\n    z = 3\n    return y + z\n\n\n"
               "class Foo:\n    def m(self):\n        pass\n\n    def n(self):\n        pass\n")
        self.commit_base({"p.py": src})
        self.put("p.py", src.replace("    z = 3\n", "    z = 3\n    w = 4\n").replace("        pass\n\n    def n",
                                                                                         "        pass\n        pass2\n\n    def n"))
        self.all_forms()

    def test_slider_cases(self):
        # inserted blocks that can slide: the chosen position must equal git's
        cases = [
            ("a\nb\nc\n", "a\nb\nb\nc\n"),
            ("x\n}\n\ny\n", "x\n}\n\nz\n}\n\ny\n"),
            ("{\n  a\n}\n{\n  b\n}\n", "{\n  a\n}\n{\n  new\n}\n{\n  b\n}\n"),
            ("1\n\n2\n\n3\n", "1\n\nnew\n\n2\n\n3\n"),
            ("if x:\n    a\n    b\n", "if x:\n    a\n    b\n    c\n    b\n"),
            ("a\n\n\nb\n", "a\n\n\n\nb\n"),
            ("foo\nbar\nfoo\nbar\n", "foo\nbar\nfoo\nbar\nfoo\nbar\n"),
        ]
        for n, (a, b) in enumerate(cases):
            self.put("s%d" % n, a)
        self.both("add", ".")
        self.both("commit", "-m", "x")
        for n, (a, b) in enumerate(cases):
            self.put("s%d" % n, b)
        self.both("diff")

    def test_random_edits_match_git(self):
        rnd = random.Random(42)
        words = ["alpha", "beta", "gamma", "", "    indented", "}", "{", "x = 1", "return", "#"]
        files = {}
        for n in range(12):
            files["r%d.txt" % n] = "".join(rnd.choice(words) + "\n" for _ in range(rnd.randint(5, 60)))
        self.commit_base(files)
        for name, content in files.items():
            lines = content.split("\n")[:-1]
            for _ in range(rnd.randint(1, 6)):
                op = rnd.random()
                pos = rnd.randint(0, len(lines))
                if op < 0.4:
                    lines[pos:pos] = [rnd.choice(words) for _ in range(rnd.randint(1, 4))]
                elif op < 0.8 and lines:
                    del lines[pos:pos + rnd.randint(1, 3)]
                elif lines:
                    lines[min(pos, len(lines) - 1)] = rnd.choice(words)
            self.put(name, "".join(l + "\n" for l in lines))
        g = self.git("diff", cwd=self.dirs["g"]).text
        u = self.ugit("diff", cwd=self.dirs["u"]).text
        self.assertEqual(g, u)
        self.both("diff", "--stat")
        self.both("diff", "--numstat")


if __name__ == "__main__":
    unittest.main()
