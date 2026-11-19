"""Scalability checks (generous bounds; they catch super-linear behaviour, not micro-timings)."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import SandboxTest, needs_git  # noqa: E402


class Perf(SandboxTest):
    def test_many_files_add_commit_status_diff(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        for i in range(3000):
            self.sb.write("r/d%d/f%d.txt" % (i % 40, i), "content %d\n" % i)
        t = time.time()
        self.assertEqual(self.ugit("add", ".", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("commit", "-q", "-m", "big", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("status", "--porcelain", cwd=cwd).text, "")
        self.sb.write("r/d1/f1.txt", "changed\n")
        self.assertEqual(self.ugit("diff", "--stat", cwd=cwd).rc, 0)
        self.assertLess(time.time() - t, 60)

    def test_large_file_diff(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        body = "".join("line number %d\n" % i for i in range(50000))
        self.sb.write("r/big.txt", body)
        self.ugit("add", "big.txt", cwd=cwd)
        self.ugit("commit", "-q", "-m", "x", cwd=cwd)
        self.sb.write("r/big.txt", body.replace("line number 25000\n", "changed\n") + "tail\n")
        t = time.time()
        r = self.ugit("diff", cwd=cwd)
        self.assertEqual(r.rc, 0)
        self.assertIn("+tail", r.text)
        self.assertLess(time.time() - t, 20)

    @needs_git
    def test_long_history_log(self):
        self.git("init", "-q", "r")
        cwd = self.sb.path("r")
        n = 3000
        lines = []
        for i in range(n):
            lines.append("commit refs/heads/master\nmark :%d\ncommitter A <a@x> %d +0000\ndata 3\nc%d\n" % (
                i + 1, 1700000000 + i, i % 10))
            if i:
                lines.append("from :%d\n" % i)
            lines.append("M 100644 inline f\ndata 2\n%d\n\n" % (i % 7))
        r = self.git("fast-import", "--quiet", cwd=cwd, stdin="".join(lines).encode())
        self.assertEqual(r.rc, 0, r.etext)
        t = time.time()
        a = self.ugit("log", "--oneline", cwd=cwd)
        self.assertLess(time.time() - t, 30)
        self.assertEqual(a.text, self.git("log", "--oneline", cwd=cwd).text)
        t = time.time()
        a = self.ugit("log", "--oneline", "--", "f", cwd=cwd)
        self.assertEqual(a.text, self.git("log", "--oneline", "--", "f", cwd=cwd).text)
        self.assertLess(time.time() - t, 60)


if __name__ == "__main__":
    unittest.main()


class Scalability(SandboxTest):
    """R32: thousands of files, megabyte-sized blobs, deep trees, wide directories, many refs."""

    def make_files(self, n, fmt="f%d.txt", per_dir=50):
        for i in range(n):
            self.sb.write(("r/d%d/" % (i // per_dir)) + fmt % i, "content of file %d\n" % i)

    def test_ten_thousand_files(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.make_files(10000, per_dir=100)
        t = time.time()
        self.assertEqual(self.ugit("add", "-A", cwd=cwd).rc, 0)
        add_time = time.time() - t
        t = time.time()
        self.assertEqual(self.ugit("commit", "-q", "-m", "many", cwd=cwd).rc, 0)
        commit_time = time.time() - t
        t = time.time()
        self.assertEqual(self.ugit("status", "--porcelain", cwd=cwd).text, "")
        status_time = time.time() - t
        self.sb.write("r/d3/f350.txt", "edited\n")
        t = time.time()
        self.assertEqual(self.ugit("status", "--porcelain", cwd=cwd).text, " M d3/f350.txt\n")
        self.assertEqual(self.ugit("ls-files", cwd=cwd).text.count("\n"), 10000)
        self.assertEqual(self.ugit("ls-tree", "-r", "HEAD", cwd=cwd).text.count("\n"), 10000)
        self.assertLess(add_time, 40)
        self.assertLess(commit_time, 40)
        self.assertLess(status_time, 10)
        self.assertLess(time.time() - t, 20)

    def test_checkout_between_large_trees(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.make_files(3000)
        self.ugit("add", "-A", cwd=cwd)
        self.ugit("commit", "-q", "-m", "one", cwd=cwd)
        self.ugit("branch", "other", cwd=cwd)
        for i in range(0, 3000, 3):
            self.sb.write(("r/d%d/" % (i // 50)) + "f%d.txt" % i, "changed %d\n" % i)
        self.ugit("commit", "-q", "-a", "-m", "two", cwd=cwd)
        t = time.time()
        self.assertEqual(self.ugit("checkout", "-q", "other", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("checkout", "-q", "master", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("merge", "-q", "other", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("status", "--porcelain", cwd=cwd).text, "")
        self.assertLess(time.time() - t, 40)

    def test_large_blob_roundtrip(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        blob = os.urandom(1 << 20) * 24  # 24 MiB, incompressible head repeated
        self.sb.write("r/big.bin", blob)
        t = time.time()
        self.assertEqual(self.ugit("add", "big.bin", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("commit", "-q", "-m", "big", cwd=cwd).rc, 0)
        r = self.ugit("cat-file", "-s", "HEAD:big.bin", cwd=cwd)
        self.assertEqual(r.text.strip(), str(len(blob)))
        os.unlink(self.sb.path("r/big.bin"))
        self.assertEqual(self.ugit("checkout", "--", "big.bin", cwd=cwd).rc, 0)
        with open(self.sb.path("r/big.bin"), "rb") as f:
            self.assertEqual(f.read(), blob)
        self.assertEqual(self.ugit("status", "--porcelain", cwd=cwd).text, "")
        self.assertLess(time.time() - t, 60)

    def test_deep_directory_nesting(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        path = "/".join("d%d" % i for i in range(120))
        self.sb.write("r/%s/leaf.txt" % path, "deep\n")
        t = time.time()
        self.assertEqual(self.ugit("add", ".", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("commit", "-q", "-m", "deep", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("ls-tree", "-r", "HEAD", cwd=cwd).text.split("\t")[1].strip(), path + "/leaf.txt")
        self.assertEqual(self.ugit("diff", "HEAD~0", cwd=cwd).rc, 0)
        self.assertLess(time.time() - t, 30)

    def test_wide_directory(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        for i in range(8000):
            self.sb.write("r/wide/%05d" % i, "%d\n" % i)
        t = time.time()
        self.assertEqual(self.ugit("add", ".", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("commit", "-q", "-m", "wide", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("status", "-s", cwd=cwd).text, "")
        self.assertLess(time.time() - t, 40)

    @needs_git
    def test_many_refs_and_packed_objects(self):
        self.git("init", "-q", "r")
        cwd = self.sb.path("r")
        self.sb.write("r/f", "x\n")
        self.git("add", ".", cwd=cwd)
        self.git("commit", "-qm", "c", cwd=cwd)
        lines = "".join("create refs/heads/b%05d HEAD\n" % i for i in range(5000))
        lines += "".join("create refs/tags/t%05d HEAD\n" % i for i in range(2000))
        self.assertEqual(self.git("update-ref", "--stdin", cwd=cwd, stdin=lines.encode()).rc, 0)
        self.git("pack-refs", "--all", "--prune", cwd=cwd)
        t = time.time()
        a = self.ugit("branch", cwd=cwd).text
        self.assertEqual(a, self.git("branch", cwd=cwd).text)
        self.assertEqual(self.ugit("tag", cwd=cwd).text, self.git("tag", cwd=cwd).text)
        self.assertEqual(self.ugit("rev-parse", "b04999", "t01999", cwd=cwd).text.count("\n"), 2)
        self.assertLess(time.time() - t, 20)

    @needs_git
    def test_large_packed_repository_reads(self):
        self.git("init", "-q", "r")
        cwd = self.sb.path("r")
        lines = []
        n = 4000
        for i in range(n):
            lines.append("commit refs/heads/master\nmark :%d\ncommitter A <a@x> %d +0000\ndata 2\nc\n" % (i + 1, 1700000000 + i))
            if i:
                lines.append("from :%d\n" % i)
            lines.append("M 100644 inline dir%d/file.txt\ndata %d\n%s\n\n" % (i % 20, len(("body %d\n" % i) * 20),
                                                                          ("body %d\n" % i) * 20))
        self.git("fast-import", "--quiet", cwd=cwd, stdin="".join(lines).encode())
        self.git("repack", "-adf", "--depth=50", "--window=50", cwd=cwd)
        t = time.time()
        self.assertEqual(self.ugit("rev-parse", "HEAD~3999", cwd=cwd).text, self.git("rev-parse", "HEAD~3999", cwd=cwd).text)
        self.assertEqual(self.ugit("ls-tree", "-r", "HEAD", cwd=cwd).text, self.git("ls-tree", "-r", "HEAD", cwd=cwd).text)
        self.assertEqual(self.ugit("log", "--format=%h", "-n", "500", cwd=cwd).text,
                         self.git("log", "--format=%h", "-n", "500", cwd=cwd).text)
        self.assertEqual(self.ugit("show", "HEAD~1000", cwd=cwd).out, self.git("show", "HEAD~1000", cwd=cwd).out)
        self.assertLess(time.time() - t, 60)


class StartupCost(SandboxTest):
    def test_command_startup_is_small(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        t = time.time()
        for _ in range(10):
            self.assertEqual(self.ugit("rev-parse", "--git-dir", cwd=cwd).rc, 0)
        self.assertLess((time.time() - t) / 10, 1.0)
