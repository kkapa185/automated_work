"""log / show / branch / tag against real git."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import PairTest, SandboxTest, needs_git  # noqa: E402


class HistoryBase(SandboxTest):
    """One repository built with real git (including merges); both tools read it."""

    def build(self):
        self.git("init", "-q", "-b", "master", "r")
        self.cwd = self.sb.path("r")
        t = [1700000000]

        def commit(msg, files=None, parents_env=None, extra=()):
            for n, c in (files or {}).items():
                self.sb.write("r/" + n, c)
            self.git("add", "-A", cwd=self.cwd)
            t[0] += 100
            env = {"GIT_AUTHOR_DATE": "@%d +0000" % t[0], "GIT_COMMITTER_DATE": "@%d +0000" % t[0]}
            r = self.git("commit", "-q", "--allow-empty", "-m", msg, *extra, cwd=self.cwd, env=env)
            self.assertEqual(r.rc, 0, r.etext)

        commit("root commit", {"a.txt": "a1\n", "d/b.txt": "b1\n"})
        commit("second\n\nbody paragraph\nwith two lines\n\n\nfinal para", {"a.txt": "a1\na2\n"})
        self.git("checkout", "-q", "-b", "feature", cwd=self.cwd)
        commit("feature one", {"f.txt": "f1\n"})
        commit("feature two", {"f.txt": "f1\nf2\n", "d/b.txt": "b2\n"})
        self.git("checkout", "-q", "master", cwd=self.cwd)
        commit("master three", {"a.txt": "a1\na2\na3\n"})
        t[0] += 100
        env = {"GIT_AUTHOR_DATE": "@%d +0000" % t[0], "GIT_COMMITTER_DATE": "@%d +0000" % t[0]}
        r = self.git("merge", "-q", "--no-ff", "-m", "Merge branch 'feature'", "feature", cwd=self.cwd, env=env)
        self.assertEqual(r.rc, 0, r.etext)
        commit("after merge", {"g.txt": "g\n"})
        self.git("tag", "light", "HEAD~1", cwd=self.cwd)
        t[0] += 10
        self.git("tag", "-a", "-m", "annotated tag message\n\nmore", "v1", "HEAD~2", cwd=self.cwd,
                 env={"GIT_COMMITTER_DATE": "@%d +0000" % t[0]})
        self.sb.write("r/utf.txt", "ü\n")
        commit("unicode subject ü ✓", {"utf.txt": "ü\n"})

    def same(self, *args, **kw):
        a = self.ugit(*args, cwd=self.cwd, **kw)
        b = self.git(*args, cwd=self.cwd, **kw)
        msg = "args=%r\ngit: %r %r %d\nugit: %r %r %d" % (args, b.text, b.etext, b.rc, a.text, a.etext, a.rc)
        self.assertEqual((a.rc, a.out), (b.rc, b.out), msg)
        self.assertEqual(a.etext.split("\n")[0], b.etext.split("\n")[0], msg)


@needs_git
class LogShow(HistoryBase):
    def setUp(self):
        super().setUp()
        self.build()

    def test_log_default_and_oneline(self):
        for a in (["log"], ["log", "--oneline"], ["log", "-n", "2"], ["log", "-2"], ["log", "-n1"],
                  ["log", "--max-count=3", "--oneline"], ["log", "--oneline", "-1"], ["log", "--reverse"],
                  ["log", "--skip=2", "--oneline"], ["log", "--oneline", "feature"], ["log", "feature"],
                  ["log", "--oneline", "master..feature"], ["log", "--oneline", "feature..master"],
                  ["log", "--oneline", "master...feature"], ["log", "--oneline", "^feature", "master"],
                  ["log", "--oneline", "--all"], ["log", "--first-parent", "--oneline"],
                  ["log", "--no-merges", "--oneline"], ["log", "--merges", "--oneline"],
                  ["log", "HEAD~2"], ["log", "v1"], ["log", "light", "--oneline"]):
            self.same(*a)

    def test_log_formats(self):
        for f in ("%H", "%h", "%T", "%t", "%P", "%p", "%s", "%b", "%B", "%an", "%ae", "%ad", "%aD", "%at",
                  "%ai", "%aI", "%as", "%cn", "%ce", "%cd", "%cD", "%ct", "%ci", "%cI", "%cs", "%n", "%%",
                  "%H %h %s %an %ae %ad", "%h|%s|%d", "%D", "%f", "%x41", "%an <%ae>%n%b",
                  "%C(red)%h%C(reset) %s"):
            self.same("log", "--format=" + f)
            self.same("log", "--pretty=format:" + f)
            self.same("log", "--pretty=tformat:" + f)

    def test_log_pretty_styles_and_dates(self):
        for a in (["log", "--pretty=oneline"], ["log", "--pretty=short"], ["log", "--pretty=full"],
                  ["log", "--pretty=fuller"], ["log", "--pretty=medium"], ["log", "--abbrev-commit"],
                  ["log", "--abbrev=10", "--oneline"], ["log", "--date=iso"], ["log", "--date=short"],
                  ["log", "--date=raw"], ["log", "--date=rfc"], ["log", "--date=iso-strict"],
                  ["log", "--date=unix"], ["log", "--format=%ad", "--date=short"],
                  ["log", "--decorate", "--oneline"], ["log", "--decorate"]):
            self.same(*a)

    def test_log_patch_and_stat(self):
        for a in (["log", "-p"], ["log", "--stat"], ["log", "--name-only"], ["log", "--name-status"],
                  ["log", "-p", "--oneline"], ["log", "--stat", "--oneline"], ["log", "-p", "-1"],
                  ["log", "-p", "--format=%h %s"], ["log", "--shortstat", "--oneline"],
                  ["log", "-s"], ["log", "--oneline", "--numstat"]):
            self.same(*a)

    def test_log_paths(self):
        for a in (["log", "--oneline", "--", "a.txt"], ["log", "--oneline", "--", "d"],
                  ["log", "--oneline", "a.txt"], ["log", "--oneline", "--", "f.txt"],
                  ["log", "--oneline", "--", "g.txt", "a.txt"], ["log", "-p", "--", "d/b.txt"],
                  ["log", "--oneline", "feature", "--", "d/b.txt"], ["log", "--oneline", "--", "nonexistent"]):
            self.same(*a)

    def test_log_errors(self):
        self.same("log", "nonexistent")
        self.same("log", "--bogus")
        self.git("init", "-q", "e")
        e = self.sb.path("e")
        a, b = self.ugit("log", cwd=e), self.git("log", cwd=e)
        self.assertEqual((a.rc, a.etext), (b.rc, b.etext))

    def test_show(self):
        for a in (["show"], ["show", "HEAD"], ["show", "HEAD~1"], ["show", "master~2"], ["show", "--stat"],
                  ["show", "--oneline"], ["show", "--oneline", "-s"], ["show", "--format=%H"],
                  ["show", "--format=%h %s", "HEAD~3"], ["show", "-s", "--format=%an"], ["show", "--name-only"],
                  ["show", "--name-status", "HEAD~4"], ["show", "HEAD:a.txt"], ["show", "HEAD:d"],
                  ["show", "HEAD^{tree}"], ["show", "v1"], ["show", "light"], ["show", "HEAD~4"],
                  ["show", "HEAD", "HEAD~1"], ["show", "nonexistent"], ["show", "HEAD:nonexistent"],
                  ["show", "--pretty=fuller", "HEAD~1"], ["show", "-U1", "HEAD~3"], ["show", "HEAD", "--", "g.txt"]):
            self.same(*a)

    def test_show_merge_commit_has_no_diff(self):
        merge = self.git("rev-parse", "HEAD~2", cwd=self.cwd).text.strip()
        out = self.ugit("show", merge, cwd=self.cwd).text
        self.assertIn("Merge: ", out)
        self.assertNotIn("diff --", out)
        self.assertTrue(out.startswith("commit " + merge))

    def test_log_known_answer_default_format(self):
        # format derived from the specification of the default log layout
        r = self.ugit("log", "-1", "--skip=7", cwd=self.cwd)
        lines = r.text.split("\n")
        self.assertRegex(lines[0], r"^commit [0-9a-f]{40}$")
        self.assertEqual(lines[1], "Author: Test Author <author@example.com>")
        self.assertEqual(lines[2], "Date:   Tue Nov 14 22:15:00 2023 +0000")
        self.assertEqual(lines[3:], ["", "    root commit", ""])

    def test_decorations_and_graph_free_output(self):
        self.same("log", "--oneline", "--decorate", "--all")
        self.same("log", "--format=%d", "--all")


@needs_git
class BranchTag(PairTest):
    def seed(self):
        self.put("a", "1\n")
        self.both("add", ".")
        self.both("commit", "-m", "one")
        self.put("a", "2\n")
        self.both("commit", "-a", "-m", "two")

    def test_branch_listing_and_create(self):
        self.both("branch")
        self.seed()
        self.both("branch")
        self.both("branch", "feature")
        self.both("branch", "zeta", "HEAD~1")
        self.both("branch", "alpha")
        self.both("branch")
        self.both("branch", "-v")
        self.both("branch", "--list")
        self.both("branch", "--list", "a*")
        self.both("branch", "--show-current")
        self.both("branch", "feature")  # exists
        self.both("branch", "bad..name")
        self.both("branch", "x", "nonexistent")
        self.both("branch", "-a")
        self.both("branch", "-r")

    def test_branch_unborn(self):
        self.both("branch", "x")
        self.both("branch", "--show-current")
        self.both("branch", "-m", "newname")

    def test_branch_delete(self):
        self.seed()
        self.both("branch", "merged")
        self.both("branch", "-d", "merged")
        self.both("branch", "-d", "merged")
        self.both("branch", "-d", "master")
        self.both_git("checkout", "-q", "-b", "other")
        self.put("o", "o\n")
        self.both("add", "o")
        self.both("commit", "-m", "other work")
        self.both_git("checkout", "-q", "master")
        self.both("branch", "-d", "other")
        self.both("branch", "-D", "other")
        self.both("branch")
        self.both("branch", "-d", "a", "b")

    def test_branch_rename(self):
        self.seed()
        self.both("branch", "-m", "renamed")
        self.both("branch")
        self.both("status")
        self.both("branch", "other")
        self.both("branch", "-m", "other", "other2")
        self.both("branch", "-m", "other2", "renamed")
        self.both("branch", "-M", "other2", "renamed")
        self.both("branch", "-m", "nonexistent", "zz")
        self.both("branch")

    def test_branch_detached_listing(self):
        self.seed()
        self.both_git("checkout", "-q", "--detach", "HEAD~1")
        self.both("branch")
        self.both("branch", "--show-current")
        self.both("branch", "-v")

    def test_tags(self):
        self.both("tag")
        self.both("tag", "v0")  # unborn
        self.seed()
        self.both("tag", "v1")
        self.both("tag", "v2", "HEAD~1")
        self.both("tag", "-a", "-m", "annotated", "v3")
        self.both("tag", "-m", "implied annotated", "v4", "HEAD~1")
        self.both("tag", "-a", "-m", "multi\nline\n\nmessage  ", "v5")
        self.both("tag")
        self.both("tag", "-l")
        self.both("tag", "-l", "v[12]")
        self.both("tag", "--list", "v*")
        self.both("tag", "v1")  # exists
        self.both("tag", "-f", "v1", "HEAD~1")
        self.both("tag", "bad name")
        self.both("tag", "x", "nonexistent")
        self.both("tag", "-d", "v1")
        self.both("tag", "-d", "v1")
        self.both("tag", "-d", "v3", "v4")
        self.both("tag")
        for n in ("v5", "v2"):
            g = self.git("cat-file", "-p", n, cwd=self.dirs["g"]).text
            u = self.git("cat-file", "-p", n, cwd=self.dirs["u"]).text
            self.assertEqual(g, u)
        self.assertEqual(self.git("rev-parse", "v5", cwd=self.dirs["g"]).text,
                         self.git("rev-parse", "v5", cwd=self.dirs["u"]).text)
        self.assertEqual(self.git("fsck", "--strict", cwd=self.dirs["u"]).rc, 0)

    def test_tag_on_tree_and_blob(self):
        self.seed()
        self.both("tag", "-a", "-m", "on tree", "treetag", "HEAD^{tree}")
        self.both("tag", "blobtag", "HEAD:a")
        self.both("tag")
        g = self.git("cat-file", "-p", "treetag", cwd=self.dirs["g"]).text
        u = self.git("cat-file", "-p", "treetag", cwd=self.dirs["u"]).text
        self.assertEqual(g, u)


if __name__ == "__main__":
    unittest.main()
