"""commit and status: ugit vs real git."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import PairTest, needs_git, sha1_object  # noqa: E402


@needs_git
class Commit(PairTest):
    def test_root_commit_and_following(self):
        self.put("a.txt", "alpha\n")
        self.put("dir/b.txt", "beta\nbeta2\n")
        self.both("add", ".")
        self.both("commit", "-m", "first commit")
        self.same_objects()
        self.put("a.txt", "alpha2\n")
        self.both("commit", "-a", "-m", "second")
        self.same_objects()
        self.both("log", "--format=%H %T %P %an %ae %cn %ce %at %ct %s")

    def test_known_commit_id(self):
        # id computed from the definition of a commit object (independent of both tools)
        self.put("hello.txt", "hello\n")
        self.both("add", "hello.txt")
        self.ugit("commit", "-m", "msg", cwd=self.dirs["u"])
        blob = sha1_object("blob", b"hello\n")
        tree = sha1_object("tree", b"100644 hello.txt\0" + bytes.fromhex(blob))
        body = ("tree %s\nauthor Test Author <author@example.com> 1700000000 +0000\n"
                "committer Test Committer <committer@example.com> 1700000000 +0000\n\nmsg\n" % tree).encode()
        self.assertEqual(self.ugit("rev-parse", "HEAD", cwd=self.dirs["u"]).text.strip(),
                         sha1_object("commit", body))

    def test_summaries(self):
        self.put("a", "1\n")
        self.put("b.sh", "#!/bin/sh\n")
        self.both("add", ".")
        self.both("commit", "-m", "base")
        os.chmod(os.path.join(self.dirs["g"], "b.sh"), 0o755)
        os.chmod(os.path.join(self.dirs["u"], "b.sh"), 0o755)
        self.put("c", "new\n")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "a"))
        self.both("add", "-A")
        self.both("commit", "-m", "mixed")
        self.same_objects()

    def test_rename_summary(self):
        body = "".join("line %d of a long enough file\n" % i for i in range(20))
        self.put("old/name.txt", body)
        self.put("keep.txt", "keep\n")
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.both("mv", "old/name.txt", "new/name.txt")
        self.both("commit", "-m", "move dir")
        self.both("mv", "new/name.txt", "new/other.txt")
        self.put("new/other.txt", body + "extra\n")
        self.both("add", "-A")
        self.both("commit", "-m", "rename+edit")
        self.same_objects()

    def test_nothing_to_commit_variants(self):
        self.both("commit", "-m", "x")  # empty repo
        self.put("a", "1\n")
        self.both("commit", "-m", "x")  # untracked only
        self.both("add", "a")
        self.both("commit", "-m", "one")
        self.both("commit", "-m", "x")  # clean
        self.put("a", "2\n")
        self.both("commit", "-m", "x")  # unstaged only
        self.put("u.txt", "u\n")
        self.both("commit", "-m", "x")

    def test_allow_empty_and_amend(self):
        self.put("a", "1\n")
        self.both("add", "a")
        self.both("commit", "-m", "one")
        self.both("commit", "--allow-empty", "-m", "empty")
        self.same_objects()
        self.both("commit", "--amend", "-m", "reworded")
        self.same_objects()
        self.put("a", "2\n")
        self.both("add", "a")
        env = {"GIT_COMMITTER_DATE": "@1700000100 +0200"}
        self.both("commit", "--amend", "--no-edit", env=env)
        self.same_objects()
        self.both("log", "--format=%H %P %s %ad %cd")

    def test_amend_unborn(self):
        self.both("commit", "--amend", "-m", "x")

    def test_messages(self):
        self.put("a", "1\n")
        self.both("add", "a")
        self.both("commit", "-m", "subject", "-m", "para two\n\n\nthree  ")
        self.same_objects()
        self.put("a", "2\n")
        self.both("commit", "-a", "-m", "  spaced   \n\n\n body line  \n\n")
        self.same_objects()
        self.both("commit", "--allow-empty", "-m", "")
        self.both("commit", "--allow-empty", "-m", "unicode ✓ ünï")
        self.same_objects()

    def test_message_from_file(self):
        self.put("msg.txt", "from file\n\nbody\n")
        self.put("a", "1\n")
        self.both("add", "a")
        self.both("commit", "-F", "msg.txt")
        self.same_objects()

    def test_author_override_and_date(self):
        self.put("a", "1\n")
        self.both("add", "a")
        self.both("commit", "--author=Other Person <other@example.org>", "-m", "x")
        self.same_objects()
        self.both("commit", "--allow-empty", "--date=2020-01-02T03:04:05 +0100", "-m", "dated")
        self.same_objects()

    def test_env_identity_variants(self):
        self.put("a", "1\n")
        self.both("add", "a")
        env = {"GIT_AUTHOR_NAME": "Zed", "GIT_AUTHOR_EMAIL": "z@z.z", "GIT_AUTHOR_DATE": "1234567890 -0530",
               "GIT_COMMITTER_NAME": "Yan", "GIT_COMMITTER_EMAIL": "y@y.y", "GIT_COMMITTER_DATE": "@1234567999 +0000"}
        self.both("commit", "-m", "x", env=env)
        self.same_objects()

    def test_config_identity(self):
        self.put("a", "1\n")
        self.both("add", "a")
        for d in self.dirs.values():
            self.git("config", "user.name", "Cfg Name", cwd=d)
            self.git("config", "user.email", "cfg@example.com", cwd=d)
        # run both without identity env, with fixed dates only
        base = {k: v for k, v in self.sb.env.items() if "NAME" not in k and "EMAIL" not in k}
        import subprocess
        cmds = {"g": ["git", "commit", "--allow-empty", "-q", "-m", "cfg"],
                "u": [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ugit"),
                      "commit", "--allow-empty", "-q", "-m", "cfg"]}
        for k, cmd in cmds.items():
            r = subprocess.run(cmd, cwd=self.dirs[k], env=base, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.same_objects()

    def test_identity_unknown(self):
        self.put("a", "1\n")
        self.both("add", "a")
        base = {k: v for k, v in self.sb.env.items() if "NAME" not in k and "EMAIL" not in k}
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ugit"),
                            "commit", "-m", "x"], cwd=self.dirs["u"], env=dict(base, EMAIL=""), capture_output=True)
        self.assertEqual(r.returncode, 128)
        self.assertIn(b"Author identity unknown", r.stderr)

    def test_commit_in_subdir_and_detached(self):
        self.put("d/a", "1\n")
        self.both("add", "d")
        self.both("commit", "-m", "one", sub="d")
        self.put("d/a", "2\n")
        self.both("commit", "-a", "-m", "two", sub="d")
        self.both_git("checkout", "-q", "--detach", "HEAD~1")
        self.put("d/a", "3\n")
        self.both("commit", "-a", "-m", "detached")
        self.same_objects()

    def test_commit_empty_message_abort(self):
        self.put("a", "1\n")
        self.both("add", "a")
        self.both("commit", "-m", "")
        self.both("commit", "-m", "   \n")

    def test_commit_a_deletes(self):
        self.put("a", "1\n")
        self.put("b", "2\n")
        self.both("add", ".")
        self.both("commit", "-m", "x")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "a"))
        self.both("commit", "-a", "-m", "del")
        self.same_objects()

    def test_symlink_and_exec(self):
        self.put("run.sh", "#!/bin/sh\n", 0o755)
        for d in self.dirs.values():
            os.symlink("run.sh", os.path.join(d, "ln"))
        self.both("add", ".")
        self.both("commit", "-m", "x")
        self.same_objects()


STATUS_ARGS = [["status"], ["status", "-s"], ["status", "--porcelain"], ["status", "-sb"],
               ["status", "--porcelain", "-b"], ["status", "-z"], ["status", "--porcelain", "-z"],
               ["status", "-uno"], ["status", "-uall"], ["status", "-s", "-uall"]]


@needs_git
class Status(PairTest):
    def check_all(self, sub=""):
        for a in STATUS_ARGS:
            self.both(*a, sub=sub)

    def test_unborn(self):
        self.check_all()
        self.put("a", "1\n")
        self.check_all()
        self.both("add", "a")
        self.check_all()

    def test_clean(self):
        self.put("a", "1\n")
        self.both("add", "a")
        self.both("commit", "-m", "x")
        self.check_all()

    def test_all_kinds(self):
        for n in ("m.txt", "d.txt", "t.txt", "keep.txt", "staged_mod.txt", "del_staged.txt", "both.txt"):
            self.put(n, "content of %s\nline2\n" % n)
        self.put("dir/inner.txt", "inner\n")
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.put("m.txt", "modified\n")
        for d in self.dirs.values():
            os.unlink(os.path.join(d, "d.txt"))
            os.unlink(os.path.join(d, "t.txt"))
            os.symlink("keep.txt", os.path.join(d, "t.txt"))
        self.put("staged_mod.txt", "staged change\n")
        self.put("new_staged.txt", "new\n")
        self.both("add", "staged_mod.txt", "new_staged.txt")
        self.both("rm", "-q", "del_staged.txt")
        self.put("both.txt", "first\n")
        self.both("add", "both.txt")
        self.put("both.txt", "second\n")
        self.put("untracked.txt", "u\n")
        self.put("newdir/a", "a\n")
        self.put("newdir/b", "b\n")
        self.put("dir/untracked_in_tracked_dir", "u\n")
        self.check_all()

    def test_renames_staged(self):
        body = "".join("this is line number %d\n" % i for i in range(30))
        self.put("a.txt", body)
        self.put("b.txt", "other\n")
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.both("mv", "a.txt", "c.txt")
        self.both("mv", "b.txt", "d/b.txt")
        self.put("c.txt", body + "more\n")
        self.check_all()
        self.both("add", "c.txt")
        self.check_all()

    def test_ignored(self):
        self.put(".gitignore", "*.log\nbuild/\n")
        self.put("x.log", "l\n")
        self.put("build/o", "o\n")
        self.put("keep", "k\n")
        self.both("add", ".gitignore")
        self.check_all()
        self.both("status", "--ignored")
        self.both("status", "--ignored", "-s")

    def test_subdir_paths(self):
        self.put("d/a", "1\n")
        self.put("d/e/b", "2\n")
        self.put("top", "t\n")
        self.both("add", ".")
        self.both("commit", "-m", "x")
        self.put("d/a", "changed\n")
        self.put("d/new", "n\n")
        self.put("top", "changed\n")
        self.put("other/u", "u\n")
        self.both("add", "top")
        self.check_all(sub="d")
        self.check_all(sub="d/e")

    def test_pathspec(self):
        self.put("a", "1\n")
        self.put("b", "2\n")
        self.both("add", ".")
        self.both("commit", "-m", "x")
        self.put("a", "changed\n")
        self.put("b", "changed\n")
        self.both("status", "a")
        self.both("status", "-s", "--", "b")

    def test_detached(self):
        self.put("a", "1\n")
        self.both("add", ".")
        self.both("commit", "-m", "x")
        self.put("a", "2\n")
        self.both("commit", "-a", "-m", "y")
        self.both_git("checkout", "-q", "--detach", "HEAD~1")
        # git reads the reflog to say "detached at"; the commit is the same here
        self.check_all()

    def test_weird_names(self):
        self.put("sp ace.txt", "1\n")
        self.put("tab\tname", "2\n")
        self.put("ünï.txt", "3\n")
        self.check_all()
        self.both("add", ".")
        self.check_all()

    def test_mode_change_and_empty_dirs(self):
        self.put("run.sh", "#!/bin/sh\n")
        self.both("add", ".")
        self.both("commit", "-m", "x")
        for d in self.dirs.values():
            os.chmod(os.path.join(d, "run.sh"), 0o755)
            os.makedirs(os.path.join(d, "emptydir"))
        self.check_all()


if __name__ == "__main__":
    unittest.main()
