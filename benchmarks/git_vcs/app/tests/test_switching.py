"""checkout / switch / restore / reset: ugit vs real git."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import PairTest, needs_git  # noqa: E402


class StateMixin:
    def state(self, d):
        g = lambda *a: self.git(*a, cwd=d).text
        files = {}
        for root, dirs, fs in os.walk(d):
            dirs[:] = [x for x in dirs if x != ".git"]
            for f in fs:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, d)
                if os.path.islink(p):
                    files[rel] = ("link", os.readlink(p))
                else:
                    files[rel] = (oct(os.stat(p).st_mode & 0o111), open(p, "rb").read())
        empty_dirs = sorted(os.path.relpath(os.path.join(r, x), d) for r, ds, _ in os.walk(d)
                            if ".git" not in r.split(os.sep) for x in ds if x != ".git"
                            and not os.listdir(os.path.join(r, x)))
        extra = {}
        for n in ("MERGE_HEAD", "MERGE_MSG", "ORIG_HEAD"):
            p = os.path.join(d, ".git", n)
            extra[n] = open(p, "rb").read() if os.path.exists(p) else None
        return {"head": open(os.path.join(d, ".git/HEAD")).read(), "rev": g("rev-parse", "HEAD"),
                "stage": g("ls-files", "-s"), "status": g("status", "--porcelain"), "files": files,
                "empty_dirs": empty_dirs, "branches": g("branch", "--list"), "extra": extra}

    def same_state(self):
        gs, us = self.state(self.dirs["g"]), self.state(self.dirs["u"])
        for k in gs:
            self.assertEqual(gs[k], us[k], "state mismatch in %s" % k)
        self.assertEqual(self.git("fsck", cwd=self.dirs["u"]).rc, 0)


@needs_git
class Switching(StateMixin, PairTest):
    def history(self):
        self.put("a.txt", "a1\n")
        self.put("dir/b.txt", "b1\n")
        self.put("run.sh", "#!/bin/sh\n", 0o755)
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.both("branch", "feature")
        self.put("a.txt", "a2\n")
        self.put("c.txt", "c\n")
        self.both("add", ".")
        self.both("commit", "-m", "master two")
        self.both("switch", "feature")
        self.put("dir/b.txt", "b-feature\n")
        self.put("new/deep/f.txt", "deep\n")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "run.sh"))
        self.both("add", "-A")
        self.both("commit", "-m", "feature work")
        self.both("switch", "master")

    def test_switch_between_branches(self):
        self.history()
        for cmd in (["checkout", "feature"], ["checkout", "master"], ["switch", "feature"],
                    ["switch", "master"], ["checkout", "master"], ["switch", "master"]):
            self.both(*cmd)
            self.same_state()

    def test_empty_dirs_removed_and_files_modes(self):
        self.history()
        self.both("checkout", "feature")
        self.same_state()
        self.assertFalse(os.path.exists(os.path.join(self.dirs["u"], "run.sh")))
        self.both("checkout", "master")
        self.assertTrue(os.access(os.path.join(self.dirs["u"], "run.sh"), os.X_OK))
        self.assertFalse(os.path.exists(os.path.join(self.dirs["u"], "new")))
        self.same_state()

    def test_carry_local_changes(self):
        self.history()
        self.put("c.txt", "locally modified\n")   # untouched by the branch difference? c.txt only in master
        self.put("untracked.txt", "u\n")
        self.both("checkout", "feature")          # c.txt would be deleted -> conflict
        self.same_state()
        self.both("checkout", "-f", "feature")
        self.same_state()

    def test_carry_non_conflicting_modifications(self):
        self.history()
        self.put("run.sh", "#!/bin/sh\n# edited\n")   # differs between branches (deleted) -> conflict
        self.put("a.txt", "a2\nlocal\n")             # master vs feature: a.txt equal in base?? differs
        self.both("checkout", "feature")
        self.same_state()

    def test_carry_clean_overlap_free(self):
        self.put("x", "1\n")
        self.put("y", "1\n")
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.both("branch", "other")
        self.put("y", "2\n")
        self.both("commit", "-a", "-m", "y2")
        self.both("checkout", "other")
        self.put("x", "local\n")
        self.both("checkout", "master")      # carries x
        self.same_state()
        self.both("switch", "other")
        self.same_state()
        self.both("checkout", "other")       # already on
        self.both("add", "x")
        self.both("checkout", "master")      # carries staged x
        self.same_state()

    def test_conflicting_local_changes(self):
        self.put("f", "1\n")
        self.put("g", "1\n")
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.both("branch", "other")
        self.put("f", "2\n")
        self.put("g", "2\n")
        self.both("commit", "-a", "-m", "both")
        self.both("checkout", "other")
        self.put("f", "local f\n")
        self.put("g", "local g\n")
        self.both("checkout", "master")
        self.same_state()
        self.both("add", "f")
        self.both("switch", "master")
        self.same_state()

    def test_untracked_overwritten(self):
        self.put("a", "1\n")
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.both("branch", "other")
        self.put("new.txt", "tracked on master\n")
        self.both("add", ".")
        self.both("commit", "-m", "add new")
        self.both("checkout", "other")
        self.put("new.txt", "untracked version\n")
        self.both("checkout", "master")
        self.same_state()
        self.put("sub/x", "u\n")
        self.both("checkout", "-f", "master")
        self.same_state()

    def test_create_branches(self):
        self.history()
        for cmd in (["checkout", "-b", "n1"], ["switch", "-c", "n2"], ["checkout", "-b", "n3", "feature"],
                    ["switch", "-c", "n4", "master~1"], ["checkout", "-b", "n1"], ["switch", "-c", "n2"],
                    ["checkout", "-B", "n1", "master"], ["switch", "-C", "n5"], ["checkout", "-b", "bad..name"],
                    ["checkout", "-b", "x", "nonexistent"], ["switch", "-c", "y", "nonexistent"],
                    ["checkout", "-b"], ["branch"]):
            self.both(*cmd)
            self.same_state()

    def test_create_branch_with_local_changes(self):
        self.history()
        self.put("a.txt", "a2\nmodified\n")
        self.both("checkout", "-b", "work")
        self.same_state()
        self.both("switch", "-c", "work2", "feature")
        self.same_state()

    def test_detached_head(self):
        self.history()
        for cmd in (["checkout", "HEAD~1"], ["status"], ["checkout", "master"], ["switch", "--detach", "feature"],
                    ["switch", "--detach"], ["checkout", "--detach", "master"], ["checkout", "feature~1"],
                    ["checkout", "feature"], ["branch"]):
            self.both(*cmd)
            self.same_state()

    def test_detach_sha_and_tag(self):
        self.history()
        self.both_git("tag", "-a", "-m", "t", "v1", "feature")
        sha = self.git("rev-parse", "HEAD~1", cwd=self.dirs["g"]).text.strip()
        self.both("checkout", sha)
        self.same_state()
        self.both("checkout", "v1")
        self.same_state()
        self.both("switch", "--detach", "v1")

    def test_switch_errors(self):
        self.history()
        for cmd in (["switch", "nonexistent"], ["switch", "HEAD~1"], ["switch"], ["checkout", "nonexistent"],
                    ["switch", "master"], ["checkout", "master"], ["switch", "-c"]):
            self.both(*cmd)
        sha = self.git("rev-parse", "HEAD", cwd=self.dirs["g"]).text.strip()
        self.both("switch", sha)

    def test_unborn_branch_switching(self):
        self.both("checkout", "-b", "newname")
        self.same_state()
        self.both("switch", "-c", "other")
        self.both("checkout", "master")
        self.both("status")

    def test_checkout_paths(self):
        self.history()
        self.put("a.txt", "dirty\n")
        self.put("dir/b.txt", "dirty b\n")
        for cmd in (["checkout", "--", "a.txt"], ["checkout", "feature", "--", "dir/b.txt"],
                    ["checkout", "feature", "--", "new"], ["checkout", "HEAD~1", "a.txt"],
                    ["checkout", "--", "nonexistent"], ["checkout", "feature", "--", "nonexistent"],
                    ["checkout", "--", "."], ["checkout", "master", "--", "run.sh"],
                    ["checkout", "feature~1", "--", "."]):
            self.both(*cmd)
            self.same_state()

    def test_checkout_paths_deleted_file(self):
        self.history()
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "a.txt"))
        self.both("checkout", "--", "a.txt")
        self.same_state()
        self.both("checkout", "a.txt")
        self.same_state()

    def test_checkout_path_in_subdir(self):
        self.history()
        self.put("dir/b.txt", "dirty\n")
        self.both("checkout", "--", "b.txt", sub="dir")
        self.same_state()
        self.put("dir/b.txt", "dirty\n")
        self.both("checkout", "feature", "--", ".", sub="dir")
        self.same_state()

    def test_symlinks_and_empty_files(self):
        self.put("t", "target\n")
        self.put("empty", "")
        for d in self.dirs.values():
            os.symlink("t", os.path.join(d, "ln"))
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.both("branch", "other")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "ln"))
            os.symlink("elsewhere", os.path.join(d, "ln"))
        self.put("empty", "now full\n")
        self.both("commit", "-a", "-m", "change")
        self.both("checkout", "other")
        self.same_state()
        self.both("checkout", "master")
        self.same_state()

    def test_file_dir_transitions(self):
        self.put("x", "file\n")
        self.both("add", ".")
        self.both("commit", "-m", "x is a file")
        self.both("branch", "other")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "x"))
        self.put("x/inner", "dir\n")
        self.both("add", "-A")
        self.both("commit", "-m", "x is a dir")
        self.both("checkout", "other")
        self.same_state()
        self.both("checkout", "master")
        self.same_state()


@needs_git
class Restore(StateMixin, PairTest):
    def seed(self):
        self.put("a", "a1\n")
        self.put("b", "b1\n")
        self.put("d/c", "c1\n")
        self.both("add", ".")
        self.both("commit", "-m", "one")
        self.put("a", "a2\n")
        self.put("b", "b2\n")
        self.both("commit", "-a", "-m", "two")

    def test_restore_worktree(self):
        self.seed()
        self.put("a", "dirty\n")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "b"))
        for cmd in (["restore", "a"], ["restore", "."], ["restore", "nonexistent"], ["restore"],
                    ["restore", "--", "d"]):
            self.both(*cmd)
            self.same_state()

    def test_restore_staged(self):
        self.seed()
        self.put("a", "staged\n")
        self.put("new", "n\n")
        self.both("add", "a", "new")
        self.both("restore", "--staged", "a")
        self.same_state()
        self.both("restore", "--staged", "new")
        self.same_state()
        self.both("add", "a")
        self.both("restore", "-S", "-W", "a")
        self.same_state()
        self.both("restore", "--staged", "nonexistent")

    def test_restore_source(self):
        self.seed()
        self.both("restore", "--source=HEAD~1", "a")
        self.same_state()
        self.both("restore", "-s", "HEAD~1", "--staged", "b")
        self.same_state()
        self.both("restore", "--source", "HEAD~1", "--staged", "--worktree", ".")
        self.same_state()
        self.both("restore", "--source=nonexistent", "a")

    def test_restore_source_removes_files(self):
        self.seed()
        self.put("later", "l\n")
        self.both("add", "later")
        self.both("commit", "-m", "later")
        self.both("restore", "--source=HEAD~1", "later")
        self.same_state()
        self.both("restore", "--source=HEAD~1", "--staged", "--worktree", "later")
        self.same_state()

    def test_restore_unborn_staged(self):
        self.put("a", "1\n")
        self.both("add", "a")
        self.both("restore", "--staged", "a")
        self.same_state()


@needs_git
class Reset(StateMixin, PairTest):
    def seed(self):
        self.put("a", "a1\n")
        self.put("d/b", "b1\n")
        self.both("add", ".")
        self.both("commit", "-m", "one")
        self.put("a", "a2\n")
        self.put("new", "n\n")
        self.both("add", ".")
        self.both("commit", "-m", "two")
        self.put("d/b", "b3\n")
        self.both("commit", "-a", "-m", "three")

    def test_modes(self):
        for mode in ("--soft", "--mixed", "--hard", None):
            self.setUp()
            self.seed()
            self.put("a", "dirty\n")
            self.put("untracked", "u\n")
            self.both("add", "a")
            self.put("a", "dirtier\n")
            args = ["reset"] + ([mode] if mode else []) + ["HEAD~2"]
            self.both(*args)
            self.same_state()
            self.both("status")
            self.both("log", "--oneline")
            self.tearDownSandbox()

    def tearDownSandbox(self):
        self.sb.cleanup()

    def test_reset_head_forms(self):
        self.seed()
        self.put("a", "dirty\n")
        for cmd in (["reset"], ["reset", "--hard"], ["reset", "HEAD"], ["reset", "--soft", "HEAD~1"],
                    ["reset", "--hard", "HEAD~1"], ["reset", "--hard", "master"], ["reset", "-q", "HEAD~1"],
                    ["reset", "--hard", "nonexistent"], ["reset", "nonexistent"]):
            self.both(*cmd)
            self.same_state()

    def test_reset_hard_removes_files_and_dirs(self):
        self.seed()
        self.both("reset", "--hard", "HEAD~2")
        self.same_state()
        self.assertFalse(os.path.exists(os.path.join(self.dirs["u"], "new")))

    def test_reset_hard_restores_deleted_and_mode(self):
        self.seed()
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "a"))
            os.chmod(os.path.join(d, "new"), 0o755)
        self.both("reset", "--hard")
        self.same_state()

    def test_reset_paths(self):
        self.seed()
        self.put("a", "staged\n")
        self.put("n2", "n2\n")
        self.both("add", "a", "n2")
        for cmd in (["reset", "a"], ["reset", "--", "n2"], ["reset", "HEAD~1", "--", "d/b"],
                    ["reset", "HEAD~2", "new"], ["reset", "--hard", "a"], ["reset", "--soft", "--", "a"],
                    ["reset", "nonexistent"], ["reset", "--", "nonexistent"]):
            self.both(*cmd)
            self.same_state()

    def test_reset_unborn(self):
        self.put("a", "1\n")
        self.both("add", "a")
        self.both("reset")
        self.same_state()
        self.both("add", "a")
        self.both("reset", "--hard")
        self.same_state()

    def test_reset_detached_and_orig_head(self):
        self.seed()
        self.both_git("checkout", "-q", "--detach", "HEAD")
        self.both("reset", "--hard", "HEAD~1")
        self.same_state()

    def test_reset_in_subdir(self):
        self.seed()
        self.put("d/b", "dirty\n")
        self.both("reset", sub="d")
        self.both("reset", "--hard", sub="d")
        self.same_state()


if __name__ == "__main__":
    unittest.main()
