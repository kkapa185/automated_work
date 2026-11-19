import hashlib
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import SandboxTest, needs_git, sha1_object  # noqa: E402
from ugitlib.index import Index, IndexEntry, write_tree  # noqa: E402
from ugitlib.repo import discover  # noqa: E402


def build_index_bytes(entries):
    """Independent encoder written from the format description (entries: path, sha, mode)."""
    body = b"DIRC" + struct.pack(">II", 2, len(entries))
    for path, sha, mode in sorted(entries):
        name = path.encode()
        raw = struct.pack(">10I", 1, 2, 3, 4, 5, 6, mode, 7, 8, 9) + bytes.fromhex(sha)
        raw += struct.pack(">H", len(name)) + name
        raw += b"\0" * (8 - len(raw) % 8)
        body += raw
    return body + hashlib.sha1(body).digest()


class IndexFormat(SandboxTest):
    def test_known_layout(self):
        sha = sha1_object("blob", b"hello\n")
        data = build_index_bytes([("b.txt", sha, 0o100644), ("a/x", sha, 0o100755)])
        idx = Index()
        idx._parse(data)
        self.assertEqual([e.path for e in idx.sorted_entries()], ["a/x", "b.txt"])
        e = idx.get("a/x")
        self.assertEqual((e.mode, e.sha, e.ctime, e.ctime_ns, e.mtime, e.mtime_ns, e.dev, e.ino, e.uid,
                          e.gid, e.size), (0o100755, sha, 1, 2, 3, 4, 5, 6, 7, 8, 9))
        self.assertEqual(idx.serialize(), data)  # byte-exact round trip incl. padding + checksum

    def test_padding_lengths(self):
        sha = "ab" * 20
        for n in range(1, 20):
            name = "n" * n
            e = IndexEntry(name, sha, 0o100644)
            raw = e.pack()
            self.assertEqual(len(raw) % 8, 0)
            self.assertGreaterEqual(len(raw), 62 + n + 1)
            self.assertLess(len(raw), 62 + n + 9)

    def test_stage_bits_and_sorting(self):
        idx = Index()
        sha = "cd" * 20
        for st in (3, 1, 2):
            idx.add(IndexEntry("f", sha, 0o100644, st))
        idx.add(IndexEntry("a", sha, 0o100644, 0))
        data = idx.serialize()
        idx2 = Index()
        idx2._parse(data)
        self.assertEqual([(e.path, e.stage) for e in idx2.sorted_entries()],
                         [("a", 0), ("f", 1), ("f", 2), ("f", 3)])
        # flags of first 'f' entry (stage 1) = 0x1000 | namelen 1
        pos = 12 + len(IndexEntry("a", sha, 0).pack())
        flags = struct.unpack(">H", data[pos + 60:pos + 62])[0]
        self.assertEqual(flags, 0x1001)

    def test_bad_checksum(self):
        data = bytearray(build_index_bytes([("a", "00" * 20, 0o100644)]))
        data[20] ^= 1
        from ugitlib.util import Fatal
        with self.assertRaises(Fatal):
            Index()._parse(bytes(data))

    def test_df_conflict_replacement(self):
        idx = Index()
        sha = "ab" * 20
        idx.add(IndexEntry("a/b", sha, 0o100644))
        idx.add(IndexEntry("a", sha, 0o100644))
        self.assertEqual([e.path for e in idx.sorted_entries()], ["a"])
        idx.add(IndexEntry("a/c", sha, 0o100644))
        self.assertEqual([e.path for e in idx.sorted_entries()], ["a/c"])

    @needs_git
    def test_git_reads_ugit_index_and_back(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.sb.write("r/a.txt", "one\n")
        self.sb.write("r/dir/b.txt", "two\n")
        self.sb.write("r/run.sh", "#!/bin/sh\n", mode=0o755)
        os.symlink("a.txt", self.sb.path("r/link"))
        self.assertEqual(self.ugit("add", ".", cwd=cwd).rc, 0)
        st = self.git("status", "--porcelain", cwd=cwd)
        self.assertEqual(st.text, "A  a.txt\nA  dir/b.txt\nA  link\nA  run.sh\n")  # nothing 'modified'
        ls = self.git("ls-files", "-s", cwd=cwd).text
        self.assertIn("100755", ls)
        self.assertIn("120000", ls)
        self.assertEqual(self.git("fsck", cwd=cwd).rc, 0)
        # git writes the index back (with extensions), ugit must still read it
        self.git("commit", "-qm", "c", cwd=cwd)
        self.git("update-index", "--refresh", cwd=cwd)
        self.assertEqual(self.ugit("ls-files", "-s", cwd=cwd).text, ls)
        self.assertEqual(self.ugit("ls-files", "-m", cwd=cwd).text, "")

    @needs_git
    def test_ugit_reads_git_index(self):
        self.git("init", "-q", "r")
        cwd = self.sb.path("r")
        for i in range(30):
            self.sb.write("r/f%02d.txt" % i, "x%d\n" % i)
        self.sb.write("r/sub/deep/ü.txt", "unicode\n")
        self.git("add", ".", cwd=cwd)
        self.git("commit", "-qm", "c", cwd=cwd)
        a = self.ugit("ls-files", "-s", cwd=cwd)
        b = self.git("ls-files", "-s", cwd=cwd)
        self.assertEqual(a.text, b.text)

    @needs_git
    def test_index_version4_and_extended_flags(self):
        self.git("init", "-q", "r")
        cwd = self.sb.path("r")
        for p in ("src/a.c", "src/b.c", "src/sub/c.c", "z"):
            self.sb.write("r/" + p, p + "\n")
        self.git("add", ".", cwd=cwd)
        self.git("update-index", "--index-version=4", cwd=cwd)
        self.assertEqual(self.ugit("ls-files", cwd=cwd).text, self.git("ls-files", cwd=cwd).text)
        self.git("update-index", "--index-version=3", "--skip-worktree", "z", cwd=cwd)
        self.assertEqual(self.ugit("ls-files", cwd=cwd).text, self.git("ls-files", cwd=cwd).text)

    @needs_git
    def test_write_tree_matches_git(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        for p in ("a", "b/c", "b/d/e", "b.txt", "b-x/y", "z"):
            self.sb.write("r/" + p, p + "\n")
        self.ugit("add", "-A", cwd=cwd)
        repo = discover(cwd, self.sb.env)
        tree = write_tree(repo, Index.load(repo))
        self.assertEqual(tree, self.git("write-tree", cwd=cwd).text.strip())

    def test_index_stat_fields_match_lstat(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        p = self.sb.write("r/f", "data\n")
        self.ugit("add", "f", cwd=cwd)
        repo = discover(cwd, self.sb.env)
        e = Index.load(repo).get("f")
        st = os.lstat(p)
        self.assertEqual((e.size, e.mtime, e.mtime_ns, e.ino, e.uid, e.gid, e.mode),
                         (st.st_size, st.st_mtime_ns // 10 ** 9, st.st_mtime_ns % 10 ** 9,
                          st.st_ino & 0xFFFFFFFF, st.st_uid, st.st_gid, 0o100644))
        self.assertEqual(e.sha, sha1_object("blob", b"data\n"))


if __name__ == "__main__":
    unittest.main()
