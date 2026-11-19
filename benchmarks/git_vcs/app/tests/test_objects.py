import os
import subprocess
import unittest
import zlib

from helpers import SandboxTest, needs_git, sha1_object

sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, sys_path)
from ugitlib.objects import ObjectStore, apply_delta, build_tree, parse_tree, parse_commit, hash_object  # noqa: E402


class KnownAnswers(unittest.TestCase):
    def test_empty_blob(self):
        self.assertEqual(hash_object("blob", b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")

    def test_hello_blob(self):
        self.assertEqual(hash_object("blob", b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_empty_tree(self):
        self.assertEqual(hash_object("tree", b""), "4b825dc642cb6eb9a060e54bf8d69288fbee4904")

    def test_tree_roundtrip_and_order(self):
        sha = "ce013625030ba8dba906f756967f9e9ca394464a"
        ents = [(0o100644, "b.c", sha), (0o40000, "b", sha), (0o100644, "b-x", sha), (0o100755, "a", sha)]
        data = build_tree(ents)
        names = [n for _, n, _ in parse_tree(data)]
        # git sorts directories as if their name ended in '/': "b-x" < "b.c" < "b/"
        self.assertEqual(names, ["a", "b-x", "b.c", "b"])
        self.assertEqual(data[:len(b"100755 a\0")], b"100755 a\0")

    def test_commit_parse(self):
        body = (b"tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904\nparent " + b"a" * 40 +
                b"\nauthor A <a@b> 1 +0000\ncommitter C <c@d> 2 +0100\n\nmsg\n")
        c = parse_commit(body)
        self.assertEqual(c.parents, ["a" * 40])
        self.assertEqual(c.committer, "C <c@d> 2 +0100")
        self.assertEqual(c.message, "msg\n")
        self.assertEqual(c.serialize(), body)

    def test_apply_delta(self):
        base = b"0123456789"
        # src size 10, dst size 8: copy off=2 size=4 ("2345"), insert "xy", copy off=8 size=2
        delta = bytes([10, 8, 0x80 | 0x01 | 0x10, 2, 4, 2]) + b"xy" + bytes([0x80 | 0x01 | 0x10, 8, 2])
        self.assertEqual(apply_delta(base, delta), b"2345xy89")


class LooseStore(SandboxTest):
    def test_write_read_and_format(self):
        self.ugit("init", "r")
        os.chdir(self.sb.root)
        objdir = os.path.join(self.sb.path("r"), ".git", "objects")
        store = ObjectStore(objdir)
        sha = store.write("blob", b"some content\n")
        self.assertEqual(sha, sha1_object("blob", b"some content\n"))
        raw = open(os.path.join(objdir, sha[:2], sha[2:]), "rb").read()
        self.assertEqual(zlib.decompress(raw), b"blob 13\0some content\n")
        self.assertEqual(store.read(sha), ("blob", b"some content\n"))
        self.assertEqual(store.find_prefix(sha[:5]), [sha])

    def test_hash_object_cli(self):
        r = self.sb.write("f", "hello\n")
        res = self.ugit("hash-object", "f")
        self.assertEqual(res.text, "ce013625030ba8dba906f756967f9e9ca394464a\n")
        self.assertEqual(res.rc, 0)

    def test_hash_object_w_and_cat_file(self):
        self.ugit("init", "r")
        self.sb.write("r/f", "hello\n")
        cwd = self.sb.path("r")
        res = self.ugit("hash-object", "-w", "f", cwd=cwd)
        sha = res.text.strip()
        self.assertTrue(os.path.exists(os.path.join(cwd, ".git/objects", sha[:2], sha[2:])))
        self.assertEqual(self.ugit("cat-file", "-p", sha, cwd=cwd).text, "hello\n")
        self.assertEqual(self.ugit("cat-file", "-t", sha, cwd=cwd).text, "blob\n")
        self.assertEqual(self.ugit("cat-file", "-s", sha, cwd=cwd).text, "6\n")
        self.assertEqual(self.ugit("cat-file", "blob", sha[:8], cwd=cwd).text, "hello\n")
        self.assertEqual(self.ugit("cat-file", "-e", sha, cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("cat-file", "-e", "0" * 40, cwd=cwd).rc, 1)
        bad = self.ugit("cat-file", "-p", "zzzz", cwd=cwd)
        self.assertEqual(bad.rc, 128)
        self.assertEqual(bad.etext, "fatal: Not a valid object name zzzz\n")

    def test_hash_object_stdin_and_type(self):
        res = self.ugit("hash-object", "--stdin", stdin=b"")
        self.assertEqual(res.text.strip(), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")
        res = self.ugit("hash-object", "-t", "tree", "--stdin", stdin=b"")
        self.assertEqual(res.text.strip(), "4b825dc642cb6eb9a060e54bf8d69288fbee4904")

    def test_hash_object_w_outside_repo(self):
        self.sb.write("f", "x")
        res = self.ugit("hash-object", "-w", "f")
        self.assertEqual(res.rc, 128)
        self.assertIn("not a git repository", res.etext)

    @needs_git
    def test_git_reads_ugit_objects_fsck(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.sb.write("r/f", "data\n")
        sha = self.ugit("hash-object", "-w", "f", cwd=cwd).text.strip()
        tree = build_tree([(0o100644, "f", sha)])
        store = ObjectStore(os.path.join(cwd, ".git/objects"))
        tsha = store.write("tree", tree)
        from ugitlib.objects import Commit
        c = Commit(tsha, [], "A <a@x> 1700000000 +0000", "A <a@x> 1700000000 +0000", "msg\n")
        csha = store.write("commit", c.serialize())
        self.assertEqual(self.git("cat-file", "-p", csha, cwd=cwd).text.splitlines()[0], "tree " + tsha)
        self.assertEqual(self.git("cat-file", "-p", sha, cwd=cwd).text, "data\n")
        with open(os.path.join(cwd, ".git/refs/heads/master"), "w") as f:
            f.write(csha + "\n")
        res = self.git("fsck", "--strict", cwd=cwd)
        self.assertEqual(res.rc, 0, res.etext)
        self.assertEqual(self.git("log", "--format=%s", cwd=cwd).text, "msg\n")

    @needs_git
    def test_ugit_reads_git_loose_objects(self):
        self.git("init", "-q", "g")
        cwd = self.sb.path("g")
        self.sb.write("g/a.txt", "alpha\n")
        self.git("add", "a.txt", cwd=cwd)
        self.git("commit", "-qm", "first", cwd=cwd)
        head = self.git("rev-parse", "HEAD", cwd=cwd).text.strip()
        self.assertEqual(self.ugit("rev-parse", "HEAD", cwd=cwd).text.strip(), head)
        self.assertEqual(self.ugit("cat-file", "-p", head, cwd=cwd).out,
                         self.git("cat-file", "-p", head, cwd=cwd).out)
        tree = self.git("rev-parse", "HEAD^{tree}", cwd=cwd).text.strip()
        self.assertEqual(self.ugit("cat-file", "-p", tree, cwd=cwd).out,
                         self.git("cat-file", "-p", tree, cwd=cwd).out)


@needs_git
class PackReading(SandboxTest):
    def make_history(self):
        self.git("init", "-q", "g")
        cwd = self.sb.path("g")
        body = "".join("line %d of the file\n" % i for i in range(200))
        for n in range(6):
            body = body.replace("line %d " % (n * 7), "LINE %d " % (n * 7)) + "extra %d\n" % n
            self.sb.write("g/big.txt", body)
            self.sb.write("g/small%d.txt" % n, "small %d\n" % n)
            self.git("add", ".", cwd=cwd)
            self.git("commit", "-qm", "c%d" % n, cwd=cwd)
        self.git("tag", "-a", "-m", "annotated", "v1", cwd=cwd)
        self.git("tag", "light", "HEAD~1", cwd=cwd)
        return cwd

    def compare_all(self, cwd):
        objs = self.git("cat-file", "--batch-all-objects", "--batch-check", cwd=cwd).text.splitlines()
        self.assertGreater(len(objs), 20)
        for line in objs:
            sha, typ, size = line.split()
            self.assertEqual(self.ugit("cat-file", "-t", sha, cwd=cwd).text.strip(), typ)
            a = self.ugit("cat-file", typ, sha, cwd=cwd).out
            b = self.git("cat-file", typ, sha, cwd=cwd).out
            self.assertEqual(a, b, sha)
            self.assertEqual(len(a), int(size))

    def test_ofs_delta_pack_and_packed_refs(self):
        cwd = self.make_history()
        self.git("repack", "-adf", "--depth=50", "--window=50", cwd=cwd)
        self.git("pack-refs", "--all", "--prune", cwd=cwd)
        self.assertFalse(os.path.exists(os.path.join(cwd, ".git/refs/heads/master")))
        packs = [f for f in os.listdir(os.path.join(cwd, ".git/objects/pack")) if f.endswith(".pack")]
        self.assertEqual(len(packs), 1)
        # make sure at least one delta exists
        verify = self.git("verify-pack", "-v", os.path.join(cwd, ".git/objects/pack", packs[0][:-5] + ".idx"), cwd=cwd)
        self.assertRegex(verify.text, r"\n\w{40} \w+\s+\d+ \d+ \d+ \d+ \w{40}")
        self.compare_all(cwd)
        head = self.git("rev-parse", "HEAD", cwd=cwd).text.strip()
        self.assertEqual(self.ugit("rev-parse", "HEAD", cwd=cwd).text.strip(), head)
        self.assertEqual(self.ugit("rev-parse", "master", "v1^{commit}", "light", cwd=cwd).text.split(),
                         self.git("rev-parse", "master", "v1^{commit}", "light", cwd=cwd).text.split())
        self.assertEqual(self.ugit("rev-parse", "HEAD~3", cwd=cwd).text,
                         self.git("rev-parse", "HEAD~3", cwd=cwd).text)

    def test_ref_delta_pack(self):
        cwd = self.make_history()
        revs = self.git("rev-list", "--objects", "--all", cwd=cwd).text
        # pack-objects without --delta-base-offset writes REF_DELTA entries
        res = self.git("pack-objects", "--window=50", "--depth=50", ".git/objects/pack/pack",
                       cwd=cwd, stdin=revs.encode())
        self.assertEqual(res.rc, 0, res.etext)
        self.git("prune-packed", cwd=cwd)
        loose = [d for d in os.listdir(os.path.join(cwd, ".git/objects")) if len(d) == 2]
        self.assertEqual(loose, [])
        # confirm the pack really has REF_DELTA entries (type 7) by scanning headers
        pdir = os.path.join(cwd, ".git/objects/pack")
        pack = [f for f in os.listdir(pdir) if f.endswith(".pack")][0]
        sys.path.insert(0, sys_path)
        from ugitlib.objects import Pack
        p = Pack(os.path.join(pdir, pack[:-5] + ".idx"))
        types = set()
        for sha in p.all_shas():
            off = p.find(bytes.fromhex(sha))
            types.add((p.data[off] >> 4) & 7)
        self.assertIn(7, types)
        self.compare_all(cwd)

    def test_abbrev_in_pack(self):
        cwd = self.make_history()
        self.git("gc", "-q", cwd=cwd)
        head = self.git("rev-parse", "HEAD", cwd=cwd).text.strip()
        self.assertEqual(self.ugit("rev-parse", head[:7], cwd=cwd).text.strip(), head)
        self.assertEqual(self.ugit("rev-parse", "--short", "HEAD", cwd=cwd).text,
                         self.git("rev-parse", "--short", "HEAD", cwd=cwd).text)


if __name__ == "__main__":
    unittest.main()
