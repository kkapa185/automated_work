"""Differential tests: ugit vs real git for add / rm / mv / ls-files / ls-tree."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import SandboxTest, needs_git  # noqa: E402


@needs_git
class Pair(SandboxTest):
    """Two identical repositories: 'g' driven by real git, 'u' by ugit."""

    def setUp(self):
        super().setUp()
        self.git("init", "-q", "g")
        self.ugit("init", "-q", "u")
        self.dirs = {"g": self.sb.path("g"), "u": self.sb.path("u")}

    def put(self, name, content="x\n", mode=None):
        for d in self.dirs.values():
            p = os.path.join(d, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(content if isinstance(content, bytes) else content.encode())
            if mode:
                os.chmod(p, mode)

    def both(self, *args, sub="", check_rc=True, stdin=None):
        """Run the same command in both repos; assert identical stdout/stderr/exit code."""
        g = self.git(*args, cwd=os.path.join(self.dirs["g"], sub), stdin=stdin)
        u = self.ugit(*args, cwd=os.path.join(self.dirs["u"], sub), stdin=stdin)
        msg = "args=%r\n--git out=%r err=%r rc=%d\n--ugit out=%r err=%r rc=%d" % (
            args, g.text, g.etext, g.rc, u.text, u.etext, u.rc)
        self.assertEqual(g.rc, u.rc, msg)
        self.assertEqual(g.text, u.text, msg)
        ge, ue = g.etext.replace(self.dirs["g"], "R"), u.etext.replace(self.dirs["u"], "R")
        if g.rc == 129:  # usage text: only the first line is part of the contract
            ge, ue = ge.split("\n")[0], ue.split("\n")[0]
        self.assertEqual(ge, ue, msg)
        return u

    def same_state(self):
        """Index content (as read by real git) and worktree must agree; ugit's index must be 'clean'."""
        gi = self.git("ls-files", "-s", cwd=self.dirs["g"]).text
        ui = self.git("ls-files", "-s", cwd=self.dirs["u"]).text
        self.assertEqual(gi, ui)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.dirs["g"]).text,
                         self.git("status", "--porcelain", cwd=self.dirs["u"]).text)
        self.assertEqual(self.ugit("ls-files", "-s", cwd=self.dirs["u"]).text, ui)
        self.assertEqual(self.ugit("ls-files", "-m", cwd=self.dirs["u"]).text,
                         self.git("ls-files", "-m", cwd=self.dirs["u"]).text)
        tree = lambda d: sorted(os.path.relpath(os.path.join(r, f), d)
                                for r, _, fs in os.walk(d) if ".git" not in r.split(os.sep)
                                for f in fs)
        self.assertEqual(tree(self.dirs["g"]), tree(self.dirs["u"]))
        self.assertEqual(self.git("fsck", cwd=self.dirs["u"]).rc, 0)

    def populate(self):
        self.put("a.txt", "alpha\n")
        self.put("b.txt", "beta\n")
        self.put("dir/c.txt", "gamma\n")
        self.put("dir/sub/d.txt", "delta\n")
        self.put("dir/sub/run.sh", "#!/bin/sh\n", 0o755)
        self.put("empty.txt", "")
        self.put("sp ace/é.txt", "unicode\n")
        for d in self.dirs.values():
            os.symlink("a.txt", os.path.join(d, "link"))

    # ---------------------------------------------------------------- add
    def test_add_variants(self):
        self.populate()
        self.both("add", "a.txt")
        self.same_state()
        self.both("add", "dir")
        self.same_state()
        self.both("add", ".")
        self.same_state()
        self.both("ls-files", "-s")

    def test_add_all_and_removals(self):
        self.populate()
        self.both("add", "-A")
        self.git("commit", "-qm", "base", cwd=self.dirs["g"])
        self.git("commit", "-qm", "base", cwd=self.dirs["u"])
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "b.txt"))
        self.put("a.txt", "changed alpha\n")
        self.put("new.txt", "new\n")
        self.both("add", "-u")
        self.same_state()
        self.both("add", "-A")
        self.same_state()
        self.put("a.txt", "again\n")
        self.both("add", "-v", "a.txt")

    def test_add_dot_subdir_and_prefix(self):
        self.populate()
        self.both("add", ".", sub="dir/sub")
        self.same_state()
        self.both("add", "../../b.txt", sub="dir/sub")
        self.both("add", "../..", sub="dir/sub")
        self.same_state()

    def test_add_ignored_and_force(self):
        self.put(".gitignore", "*.log\nbuild/\n")
        self.put("x.log", "l\n")
        self.put("build/o", "o\n")
        self.put("ok.txt", "ok\n")
        self.both("add", "x.log", "ok.txt")
        self.same_state()
        self.both("add", "build")
        self.both("add", ".")
        self.same_state()
        self.both("add", "-f", "x.log")
        self.same_state()

    def test_add_errors(self):
        self.populate()
        self.both("add", "nonexistent")
        self.both("add", "a.txt", "nonexistent")
        self.same_state()
        self.both("add")
        self.both("add", "../outside")

    def test_add_glob_pathspec(self):
        self.populate()
        self.both("add", "*.txt")
        self.same_state()
        self.both("add", "dir/*/d.txt")
        self.same_state()
        self.both("add", ":(exclude)b.txt", ".")
        self.same_state()

    def test_add_mode_change_and_symlink_change(self):
        self.populate()
        self.both("add", "-A")
        for d in self.dirs.values():
            os.chmod(os.path.join(d, "a.txt"), 0o755)
            os.unlink(os.path.join(d, "link"))
            os.symlink("b.txt", os.path.join(d, "link"))
        self.both("add", "-A")
        self.same_state()

    def test_add_file_dir_replacement(self):
        self.put("x/y.txt", "y\n")
        self.both("add", "-A")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "x/y.txt"))
            os.rmdir(os.path.join(d, "x"))
        self.put("x", "now a file\n")
        self.both("add", "-A")
        self.same_state()
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "x"))
        self.put("x/z.txt", "z\n")
        self.both("add", "-A")
        self.same_state()

    def test_add_dry_run(self):
        self.populate()
        self.both("add", "-n", ".")
        self.same_state()

    # ---------------------------------------------------------------- rm
    def committed(self):
        self.populate()
        self.both("add", "-A")
        for d in self.dirs.values():
            self.git("commit", "-qm", "base", cwd=d)

    def test_rm_basic(self):
        self.committed()
        self.both("rm", "a.txt")
        self.same_state()
        self.both("rm", "--cached", "b.txt")
        self.same_state()
        self.both("rm", "-r", "dir")
        self.same_state()

    def test_rm_requires_r_and_unmatch(self):
        self.committed()
        self.both("rm", "dir")
        self.both("rm", "nope")
        self.both("rm", "--ignore-unmatch", "nope")
        self.both("rm", "-n", "-r", "dir")
        self.both("rm", "-q", "a.txt")
        self.same_state()

    def test_rm_safety_checks(self):
        self.committed()
        self.put("a.txt", "local edit\n")
        self.both("rm", "a.txt")
        self.both("rm", "--cached", "a.txt")
        self.same_state()
        self.both("add", "a.txt")
        self.put("a.txt", "second edit\n")
        self.both("rm", "a.txt")
        self.both("rm", "--cached", "a.txt")
        self.both("rm", "-f", "a.txt")
        self.same_state()

    def test_rm_staged_new_and_multiple(self):
        self.committed()
        self.put("n1.txt", "n1\n")
        self.put("n2.txt", "n2\n")
        self.both("add", "n1.txt", "n2.txt")
        self.both("rm", "n1.txt", "n2.txt")
        self.both("rm", "--cached", "n1.txt")
        self.put("b.txt", "mod b\n")
        self.put("dir/c.txt", "mod c\n")
        self.both("rm", "b.txt", "dir/c.txt")
        self.same_state()

    def test_rm_already_deleted_and_prunes_dirs(self):
        self.committed()
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "a.txt"))
        self.both("rm", "a.txt")
        self.both("rm", "dir/sub/d.txt", "dir/sub/run.sh")
        self.same_state()
        self.assertFalse(os.path.exists(os.path.join(self.dirs["u"], "dir/sub")))

    # ---------------------------------------------------------------- mv
    def test_mv_file_and_dir(self):
        self.committed()
        self.both("mv", "a.txt", "renamed.txt")
        self.same_state()
        self.both("mv", "b.txt", "dir")
        self.same_state()
        self.both("mv", "dir", "moved")
        self.same_state()
        self.both("mv", "-v", "empty.txt", "e2.txt")
        self.same_state()

    def test_mv_errors(self):
        self.committed()
        self.put("untracked.txt", "u\n")
        self.both("mv", "nope", "x")
        self.both("mv", "untracked.txt", "x")
        self.both("mv", "a.txt", "b.txt")
        self.both("mv", "a.txt", "b.txt", "c.txt")
        self.both("mv", "a.txt")
        self.both("mv", "a.txt", "nodir/a.txt")
        self.both("mv", "-f", "a.txt", "b.txt")
        self.same_state()

    def test_mv_multiple_into_dir_and_modified(self):
        self.committed()
        self.put("a.txt", "edited\n")
        self.both("mv", "a.txt", "b.txt", "dir")
        self.same_state()

    # ---------------------------------------------------------------- ls-files
    def test_ls_files_modes(self):
        self.committed()
        self.put("a.txt", "mod\n")
        self.put("new.txt", "new\n")
        self.put("dir/new2.txt", "new\n")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "b.txt"))
        self.put(".gitignore", "ign*\n")
        self.put("ignored.txt", "i\n")
        self.put("newdir/f1", "1\n")
        self.put("newdir/f2", "2\n")
        for args in (["ls-files"], ["ls-files", "-s"], ["ls-files", "-m"], ["ls-files", "-d"],
                     ["ls-files", "-o"], ["ls-files", "-o", "--exclude-standard"],
                     ["ls-files", "-c", "-o"], ["ls-files", "-m", "-d"], ["ls-files", "-z"],
                     ["ls-files", "dir"], ["ls-files", "dir/"], ["ls-files", "*.txt"],
                     ["ls-files", "--", "a.txt", "dir/c.txt"], ["ls-files", "-o", "--directory"],
                     ["ls-files", "-o", "--directory", "--exclude-standard"],
                     ["ls-files", "--error-unmatch", "a.txt"], ["ls-files", "--error-unmatch", "zz"],
                     ["ls-files", "-i", "-o", "--exclude-standard"], ["ls-files", "-u"],
                     ["ls-files", "-s", "dir/sub"]):
            self.both(*args)

    def test_ls_files_in_subdir(self):
        self.committed()
        self.put("dir/new.txt", "n\n")
        for args in (["ls-files"], ["ls-files", "-s"], ["ls-files", "--full-name"], ["ls-files", "-o"],
                     ["ls-files", "sub"], ["ls-files", "../a.txt"], ["ls-files", "-m"]):
            self.both(*args, sub="dir")

    def test_ls_files_quoting(self):
        self.put("we\"ird\tname.txt", "1\n")
        self.put("ünï.txt", "2\n")
        self.both("add", "-A")
        self.both("ls-files")
        self.both("ls-files", "-z")
        self.both("ls-files", "-s")

    # ---------------------------------------------------------------- ls-tree
    def test_ls_tree(self):
        self.committed()
        for args in (["ls-tree", "HEAD"], ["ls-tree", "-r", "HEAD"], ["ls-tree", "-t", "HEAD"],
                     ["ls-tree", "-r", "-t", "HEAD"], ["ls-tree", "-d", "HEAD"],
                     ["ls-tree", "-r", "-d", "HEAD"], ["ls-tree", "HEAD", "dir"],
                     ["ls-tree", "HEAD", "dir/"], ["ls-tree", "-r", "HEAD", "dir"],
                     ["ls-tree", "-r", "HEAD", "dir/sub"], ["ls-tree", "HEAD", "dir/sub/d.txt"],
                     ["ls-tree", "-t", "-r", "HEAD", "dir/sub/d.txt"], ["ls-tree", "HEAD", "a.txt", "dir"],
                     ["ls-tree", "--name-only", "HEAD"], ["ls-tree", "--name-only", "-r", "HEAD"],
                     ["ls-tree", "-l", "HEAD"], ["ls-tree", "-l", "-r", "HEAD"], ["ls-tree", "-z", "HEAD"],
                     ["ls-tree", "--abbrev", "HEAD"], ["ls-tree", "HEAD:dir"], ["ls-tree", "HEAD^{tree}"],
                     ["ls-tree", "HEAD", "nonexistent"], ["ls-tree", "nonexistent"], ["ls-tree", "HEAD:a.txt"],
                     ["ls-tree", "--full-name", "HEAD"], ["ls-tree", "--name-status", "HEAD"]):
            self.both(*args)

    def test_ls_tree_subdir_and_quoting(self):
        self.committed()
        for args in (["ls-tree", "HEAD"], ["ls-tree", "-r", "HEAD"], ["ls-tree", "--full-name", "HEAD"],
                     ["ls-tree", "--full-tree", "HEAD"], ["ls-tree", "HEAD", "sub"],
                     ["ls-tree", "HEAD", "../a.txt"]):
            self.both(*args, sub="dir")

    def test_index_path_revision(self):
        self.committed()
        self.put("a.txt", "staged version\n")
        self.both("add", "a.txt")
        u = self.ugit("rev-parse", ":a.txt", cwd=self.dirs["u"])
        g = self.git("rev-parse", ":a.txt", cwd=self.dirs["g"])
        self.assertEqual(u.text, g.text)
        self.assertEqual(self.ugit("cat-file", "-p", ":a.txt", cwd=self.dirs["u"]).text, "staged version\n")
        self.assertEqual(self.ugit("rev-parse", ":0:a.txt", cwd=self.dirs["u"]).text, g.text)


class NoGitNeeded(SandboxTest):
    """Behaviour that is asserted from the specification, not from git."""

    def test_add_ls_files_roundtrip(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.sb.write("r/hello.txt", "hello\n")
        self.assertEqual(self.ugit("add", "hello.txt", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("ls-files", "-s", cwd=cwd).text,
                         "100644 ce013625030ba8dba906f756967f9e9ca394464a 0\thello.txt\n")
        self.assertEqual(self.ugit("cat-file", "-p", ":hello.txt", cwd=cwd).text, "hello\n")

    def test_add_missing_path_fatal(self):
        self.ugit("init", "r")
        res = self.ugit("add", "nope", cwd=self.sb.path("r"))
        self.assertEqual((res.rc, res.etext), (128, "fatal: pathspec 'nope' did not match any files\n"))

    def test_rm_and_mv_roundtrip(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.sb.write("r/a", "a\n")
        self.ugit("add", "a", cwd=cwd)
        self.assertEqual(self.ugit("mv", "a", "b", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("ls-files", cwd=cwd).text, "b\n")
        self.assertTrue(os.path.exists(self.sb.path("r/b")))
        res = self.ugit("rm", "--cached", "b", cwd=cwd)
        self.assertEqual(res.text, "rm 'b'\n")
        self.assertEqual(self.ugit("ls-files", cwd=cwd).text, "")
        self.assertTrue(os.path.exists(self.sb.path("r/b")))

    def test_bare_repo_rejects_add(self):
        self.ugit("init", "--bare", "b.git")
        res = self.ugit("add", "x", cwd=self.sb.path("b.git"))
        self.assertEqual(res.rc, 128)
        self.assertIn("this operation must be run in a work tree", res.etext)


if __name__ == "__main__":
    unittest.main()
