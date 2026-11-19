"""R29: error messages and exit codes (compared with real git where it is available)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import PairTest, SandboxTest, needs_git  # noqa: E402

NOT_A_REPO = "fatal: not a git repository (or any of the parent directories): .git\n"

COMMANDS_NEEDING_REPO = [
    ["add", "x"], ["rm", "x"], ["mv", "a", "b"], ["commit", "-m", "x"], ["status"], ["diff"], ["diff", "--cached"],
    ["log"], ["show"], ["cat-file", "-p", "HEAD"], ["ls-files"], ["ls-tree", "HEAD"], ["rev-parse", "HEAD"],
    ["branch"], ["checkout", "x"], ["switch", "x"], ["merge", "x"], ["tag"], ["reset"], ["restore", "x"],
    ["config", "--list"] if False else ["hash-object", "-w", "/dev/null"],
]


class OutsideRepository(SandboxTest):
    def test_every_command_reports_missing_repository(self):
        for cmd in COMMANDS_NEEDING_REPO:
            r = self.ugit(*cmd)
            self.assertEqual((r.rc, r.etext, r.out), (128, NOT_A_REPO, b""), cmd)

    def test_exact_message_from_the_ticket(self):
        r = self.ugit("status")
        self.assertEqual(r.rc, 128)
        self.assertEqual(r.etext, "fatal: not a git repository (or any of the parent directories): .git\n")

    def test_commands_that_work_without_a_repository(self):
        self.assertEqual(self.ugit("hash-object", "--stdin", stdin=b"hello\n").text.strip(),
                         "ce013625030ba8dba906f756967f9e9ca394464a")
        self.assertEqual(self.ugit("init", "x").rc, 0)
        self.assertEqual(self.ugit("config", "--list").rc, 0)

    def test_nothing_to_commit_exit_status_one(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.sb.write("r/a", "x\n")
        self.ugit("add", "a", cwd=cwd)
        self.ugit("commit", "-m", "one", cwd=cwd)
        r = self.ugit("commit", "-m", "two", cwd=cwd)
        self.assertEqual(r.rc, 1)
        self.assertIn("nothing to commit, working tree clean", r.text)

    def test_unknown_command_and_no_command(self):
        r = self.ugit("frobnicate")
        self.assertEqual((r.rc, r.etext), (1, "git: 'frobnicate' is not a git command. See 'git --help'.\n"))
        self.assertEqual(self.ugit().rc, 1)

    def test_internal_errors_never_show_a_traceback(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        with open(os.path.join(cwd, ".git", "index"), "wb") as f:
            f.write(b"not an index at all, just junk bytes here....")
        r = self.ugit("status", cwd=cwd)
        self.assertEqual(r.rc, 128)
        self.assertTrue(r.etext.startswith("fatal: "), r.etext)
        self.assertNotIn("Traceback", r.etext)
        os.unlink(os.path.join(cwd, ".git", "index"))
        with open(os.path.join(cwd, ".git", "refs", "heads", "master"), "w") as f:
            f.write("0123456789012345678901234567890123456789\n")
        r = self.ugit("log", cwd=cwd)
        self.assertNotIn("Traceback", r.etext)
        self.assertNotEqual(r.rc, 0)

    def test_corrupt_object_is_reported_not_crashed(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.sb.write("r/a", "x\n")
        sha = self.ugit("hash-object", "-w", "a", cwd=cwd).text.strip()
        p = os.path.join(cwd, ".git", "objects", sha[:2], sha[2:])
        os.chmod(p, 0o644)
        with open(p, "wb") as f:
            f.write(b"garbage")
        r = self.ugit("cat-file", "-p", sha, cwd=cwd)
        self.assertNotIn("Traceback", r.etext)
        self.assertEqual(r.rc, 128)


@needs_git
class ErrorsAgainstGit(PairTest):
    def seed(self):
        self.put("a", "1\n")
        self.put("d/b", "2\n")
        self.both("add", ".")
        self.both("commit", "-m", "one")

    def test_common_usage_and_argument_errors(self):
        self.seed()
        for cmd in (["add", "--bogus"], ["commit", "--bogus"], ["rm"], ["mv"], ["mv", "a"], ["branch", "-d"],
                    ["tag", "--bogus"], ["checkout", "--bogus"], ["reset", "--bogus"], ["merge", "--bogus"],
                    ["status", "--bogus"], ["init", "--bogus"], ["ls-files", "--bogus"], ["ls-tree"],
                    ["cat-file"], ["cat-file", "-p"], ["hash-object", "nonexistent-file"], ["rev-parse", "--verify"],
                    ["show", "nonexistent"], ["log", "nonexistent"], ["diff", "nonexistent"], ["restore"],
                    ["switch"], ["config"], ["config", "a b"], ["commit", "-F", "nofile"], ["reset", "--hard", "x", "y"]):
            self.both(*cmd)

    def test_status_codes_for_diff_and_commit(self):
        self.seed()
        self.both("diff", "--exit-code")
        self.put("a", "2\n")
        self.both("diff", "--exit-code")
        self.both("diff", "--quiet")
        self.both("commit", "-m", "nothing staged")
        self.both("ls-files", "--error-unmatch", "nonexistent")
        self.both("cat-file", "-e", "0" * 40)
        self.both("rev-parse", "--verify", "-q", "nonexistent")
        self.both("config", "--get", "no.such.key")
        self.both("branch", "-d", "nonexistent")
        self.both("tag", "-d", "nonexistent")

    def test_checkout_style_errors(self):
        self.seed()
        for cmd in (["checkout", "nonexistent"], ["switch", "nonexistent"], ["checkout", "-b", "master"],
                    ["branch", "master"], ["branch", "bad name"], ["tag", "bad..tag"], ["merge", "nonexistent"],
                    ["reset", "--hard", "nonexistent"], ["restore", "--source=nonexistent", "a"],
                    ["commit", "--amend", "--bogus"], ["rm", "nonexistent"], ["mv", "nonexistent", "x"],
                    ["add", "nonexistent"], ["show", "HEAD:nonexistent"], ["ls-tree", "nonexistent"]):
            self.both(*cmd)

    def test_git_dir_and_work_tree_environment(self):
        self.seed()
        outside = self.sb.path("elsewhere")
        os.makedirs(outside)
        for tool, d in (("git", self.dirs["g"]), ("ugit", self.dirs["u"])):
            env = {"GIT_DIR": os.path.join(d, ".git"), "GIT_WORK_TREE": d}
            run = self.git if tool == "git" else self.ugit
            with open(os.path.join(d, "a"), "w") as f:
                f.write("changed via env\n")
            r = run("status", "--porcelain", cwd=outside, env=env)
            self.assertEqual((r.rc, r.text), (0, " M a\n"), tool)
            r = run("add", "a", cwd=outside, env=env)
            self.assertEqual(r.rc, 0, (tool, r.etext))
            r = run("commit", "-q", "-m", "via env", cwd=outside, env=env)
            self.assertEqual(r.rc, 0, (tool, r.etext))
        self.same_head()

    def same_head(self):
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.dirs["g"]).text,
                         self.git("rev-parse", "HEAD", cwd=self.dirs["u"]).text)

    def test_git_dir_without_work_tree_uses_cwd(self):
        self.seed()
        for d in self.dirs.values():
            with open(os.path.join(d, "a"), "w") as f:
                f.write("x\n")
        env_g = {"GIT_DIR": os.path.join(self.dirs["g"], ".git")}
        env_u = {"GIT_DIR": os.path.join(self.dirs["u"], ".git")}
        g = self.git("status", "--porcelain", cwd=self.dirs["g"], env=env_g)
        u = self.ugit("status", "--porcelain", cwd=self.dirs["u"], env=env_u)
        self.assertEqual((g.rc, g.text), (u.rc, u.text))

    def test_dash_C_and_git_dir_options(self):
        self.seed()
        outside = self.sb.path("o2")
        os.makedirs(outside)
        for tool, d in (("git", self.dirs["g"]), ("ugit", self.dirs["u"])):
            run = self.git if tool == "git" else self.ugit
            r = run("-C", d, "log", "--oneline", cwd=outside)
            self.assertEqual(r.rc, 0, tool)
            r = run("--git-dir=" + os.path.join(d, ".git"), "--work-tree=" + d, "status", "--porcelain", cwd=outside)
            self.assertEqual((r.rc, r.text), (0, ""), tool)

    def test_not_a_repo_matches_git_for_subdirectory_of_non_repo(self):
        d = self.sb.path("plain")
        os.makedirs(os.path.join(d, "sub"))
        g = self.git("status", cwd=os.path.join(d, "sub"))
        u = self.ugit("status", cwd=os.path.join(d, "sub"))
        self.assertEqual((g.rc, g.etext), (u.rc, u.etext))


if __name__ == "__main__":
    unittest.main()
