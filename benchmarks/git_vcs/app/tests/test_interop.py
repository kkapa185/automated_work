"""R30: ugit and real git operating on the same repositories, in both directions."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import SandboxTest, needs_git  # noqa: E402


@needs_git
class Interop(SandboxTest):
    def setUp(self):
        super().setUp()
        self.git("init", "-q", "r")
        self.cwd = self.sb.path("r")
        self.n = 0

    def tick(self):
        self.n += 60
        d = "@%d +0000" % (1700000000 + self.n)
        return {"GIT_AUTHOR_DATE": d, "GIT_COMMITTER_DATE": d}

    def commit_with(self, tool, name, content, msg):
        self.sb.write("r/" + name, content)
        run = self.git if tool == "git" else self.ugit
        self.assertEqual(run("add", name, cwd=self.cwd).rc, 0)
        r = run("commit", "-q", "-m", msg, cwd=self.cwd, env=self.tick())
        self.assertEqual(r.rc, 0, r.etext)

    def test_alternating_tools_on_one_repository(self):
        for i in range(8):
            tool = "git" if i % 2 == 0 else "ugit"
            self.commit_with(tool, "f%d.txt" % (i % 3), "".join("line %d.%d\n" % (i, j) for j in range(5)), "c%d" % i)
            self.assertEqual(self.git("status", "--porcelain", cwd=self.cwd).text, "")
            self.assertEqual(self.ugit("status", "--porcelain", cwd=self.cwd).text, "")
        self.assertEqual(self.ugit("log", "--format=%H %s", cwd=self.cwd).text,
                         self.git("log", "--format=%H %s", cwd=self.cwd).text)
        self.assertEqual(self.git("fsck", "--strict", cwd=self.cwd).rc, 0)

    def test_ugit_after_git_gc_with_deltas(self):
        for i in range(6):
            self.commit_with("git", "big.txt", "".join("row %d\n" % j for j in range(300)) + "v%d\n" % i, "v%d" % i)
        self.git("gc", "-q", "--aggressive", cwd=self.cwd)
        self.assertEqual(len(os.listdir(os.path.join(self.cwd, ".git/objects/pack"))) >= 2, True)
        self.commit_with("ugit", "big.txt", "changed after gc\n", "after gc")
        self.sb.write("r/other.txt", "x\n")
        self.assertEqual(self.ugit("add", ".", cwd=self.cwd).rc, 0)
        self.assertEqual(self.ugit("diff", "--cached", "--stat", cwd=self.cwd).text,
                         self.git("diff", "--cached", "--stat", cwd=self.cwd).text)
        for rev in ("HEAD~1", "HEAD~4:big.txt", "HEAD~5"):
            self.assertEqual(self.ugit("show", rev, cwd=self.cwd).out, self.git("show", rev, cwd=self.cwd).out)
        self.assertEqual(self.ugit("checkout", "-q", "HEAD~3", cwd=self.cwd).rc, 0)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.cwd).text, "A  other.txt\n")
        self.assertEqual(self.git("fsck", cwd=self.cwd).rc, 0)

    def test_packed_refs_written_by_git(self):
        self.commit_with("git", "a", "1\n", "one")
        self.git("branch", "feat", cwd=self.cwd)
        self.git("tag", "-a", "-m", "t", "v1", cwd=self.cwd)
        self.commit_with("git", "a", "2\n", "two")
        self.git("pack-refs", "--all", "--prune", cwd=self.cwd)
        self.assertEqual(self.ugit("branch", cwd=self.cwd).text, self.git("branch", cwd=self.cwd).text)
        self.assertEqual(self.ugit("tag", cwd=self.cwd).text, "v1\n")
        self.assertEqual(self.ugit("rev-parse", "v1^{commit}", "feat", cwd=self.cwd).text,
                         self.git("rev-parse", "v1^{commit}", "feat", cwd=self.cwd).text)
        # updating a packed ref with ugit must shadow the packed value
        self.assertEqual(self.ugit("checkout", "-q", "feat", cwd=self.cwd).rc, 0)
        self.commit_with("ugit", "b", "b\n", "on feat")
        self.assertEqual(self.git("rev-parse", "feat", cwd=self.cwd).text, self.ugit("rev-parse", "HEAD", cwd=self.cwd).text)
        self.assertEqual(self.ugit("checkout", "-q", "master", cwd=self.cwd).rc, 0)
        self.assertEqual(self.ugit("branch", "-d", "feat", cwd=self.cwd).rc, 1)  # not merged
        self.assertEqual(self.ugit("branch", "-D", "feat", cwd=self.cwd).rc, 0)
        self.assertNotIn("feat", self.git("branch", cwd=self.cwd).text)

    def test_ugit_repository_is_cloneable_and_fsck_clean(self):
        self.ugit("init", "-q", "u")
        u = self.sb.path("u")
        for i in range(4):
            self.sb.write("u/f%d" % i, "content %d\n" % i)
            self.ugit("add", ".", cwd=u)
            self.ugit("commit", "-q", "-m", "c%d" % i, cwd=u, env=self.tick())
        self.ugit("branch", "side", cwd=u)
        self.ugit("tag", "-a", "-m", "release", "v1", cwd=u)
        self.assertEqual(self.git("fsck", "--strict", cwd=u).rc, 0)
        r = self.git("clone", "-q", u, self.sb.path("clone"))
        self.assertEqual(r.rc, 0, r.etext)
        self.assertEqual(self.git("log", "--format=%H", cwd=self.sb.path("clone")).text,
                         self.ugit("log", "--format=%H", cwd=u).text)
        self.assertEqual(self.git("rev-parse", "v1", cwd=self.sb.path("clone")).text,
                         self.ugit("rev-parse", "v1", cwd=u).text)

    def test_index_written_by_ugit_survives_git_operations_and_back(self):
        self.commit_with("git", "a", "1\n", "one")
        self.sb.write("r/new1", "n1\n")
        self.sb.write("r/dir/new2", "n2\n")
        self.ugit("add", ".", cwd=self.cwd)
        self.assertEqual(self.git("diff", "--cached", "--name-only", cwd=self.cwd).text, "dir/new2\nnew1\n")
        self.git("stash", "-q", cwd=self.cwd) if False else None
        self.git("commit", "-q", "-m", "by git", cwd=self.cwd, env=self.tick())
        self.git("reset", "-q", "--hard", "HEAD~1", cwd=self.cwd)
        self.assertEqual(self.ugit("status", "--porcelain", cwd=self.cwd).text, "")
        self.assertEqual(self.ugit("checkout", "-q", "master", "--", ".", cwd=self.cwd).rc, 0)

    def test_merge_conflict_state_shared(self):
        self.commit_with("git", "f", "1\n2\n3\n", "base")
        self.git("checkout", "-q", "-b", "topic", cwd=self.cwd)
        self.commit_with("git", "f", "1\nT\n3\n", "theirs")
        self.git("checkout", "-q", "master", cwd=self.cwd)
        self.commit_with("git", "f", "1\nO\n3\n", "ours")
        r = self.ugit("merge", "topic", cwd=self.cwd)
        self.assertEqual(r.rc, 1)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.cwd).text, "UU f\n")
        self.sb.write("r/f", "resolved\n")
        self.git("add", "f", cwd=self.cwd)
        r = self.git("commit", "-q", "--no-edit", cwd=self.cwd, env=self.tick())
        self.assertEqual(r.rc, 0, r.etext)
        self.assertEqual(self.ugit("log", "--format=%p", "-1", cwd=self.cwd).text.count(" "), 1)
        self.assertEqual(self.git("fsck", cwd=self.cwd).rc, 0)

    def test_reflog_written_by_ugit_is_readable_by_git(self):
        self.commit_with("ugit", "a", "1\n", "one")
        self.ugit("checkout", "-q", "-b", "x", cwd=self.cwd)
        self.commit_with("ugit", "b", "2\n", "two")
        out = self.git("reflog", cwd=self.cwd).text
        self.assertIn("checkout: moving from master to x", out)
        self.assertIn("commit (initial): one", out)
        self.assertEqual(self.git("rev-parse", "x@{1}", cwd=self.cwd).rc, 0)
        self.assertEqual(self.ugit("checkout", "-", cwd=self.cwd).rc, 0)
        self.assertEqual(self.git("symbolic-ref", "HEAD", cwd=self.cwd).text, "refs/heads/master\n")


if __name__ == "__main__":
    unittest.main()
