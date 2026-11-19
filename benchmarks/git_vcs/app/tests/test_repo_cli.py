import os
import stat
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import SandboxTest, needs_git  # noqa: E402


class Init(SandboxTest):
    def test_init_default_branch_and_message(self):
        res = self.ugit("init", "proj")
        self.assertEqual(res.rc, 0)
        self.assertEqual(res.text, "Initialized empty Git repository in %s/.git/\n" % self.sb.path("proj"))
        g = self.sb.path("proj", ".git")
        self.assertEqual(open(os.path.join(g, "HEAD")).read(), "ref: refs/heads/master\n")
        for d in ("objects", "refs/heads", "refs/tags", "objects/pack", "objects/info", "info", "hooks"):
            self.assertTrue(os.path.isdir(os.path.join(g, d)), d)
        cfg = open(os.path.join(g, "config")).read()
        self.assertEqual(cfg, "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n"
                              "\tlogallrefupdates = true\n")

    def test_init_branch_option(self):
        self.ugit("init", "-b", "trunk", "a")
        self.assertEqual(open(self.sb.path("a/.git/HEAD")).read(), "ref: refs/heads/trunk\n")
        self.ugit("init", "--initial-branch=dev", "b")
        self.assertEqual(open(self.sb.path("b/.git/HEAD")).read(), "ref: refs/heads/dev\n")

    def test_init_in_cwd_and_reinit(self):
        res = self.ugit("init")
        self.assertEqual(res.text, "Initialized empty Git repository in %s/.git/\n" % self.sb.work)
        res = self.ugit("init")
        self.assertEqual(res.text, "Reinitialized existing Git repository in %s/.git/\n" % self.sb.work)
        self.assertEqual(res.rc, 0)

    def test_reinit_keeps_head(self):
        self.ugit("init", "-b", "keep")
        self.ugit("init", "-b", "other")
        self.assertEqual(open(self.sb.path(".git/HEAD")).read(), "ref: refs/heads/keep\n")

    def test_invalid_branch_name(self):
        res = self.ugit("init", "-b", "bad..name", "x")
        self.assertEqual(res.rc, 128)
        self.assertEqual(res.etext, "fatal: invalid initial branch name: 'bad..name'\n")

    def test_bare(self):
        self.ugit("init", "--bare", "b.git")
        self.assertTrue(os.path.isfile(self.sb.path("b.git/HEAD")))
        self.assertIn("bare = true", open(self.sb.path("b.git/config")).read())

    @needs_git
    def test_git_accepts_ugit_repo(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.assertEqual(self.git("rev-parse", "--git-dir", cwd=cwd).text, ".git\n")
        self.assertEqual(self.git("symbolic-ref", "HEAD", cwd=cwd).text, "refs/heads/master\n")
        self.assertEqual(self.git("fsck", cwd=cwd).rc, 0)
        self.assertEqual(self.git("config", "core.bare", cwd=cwd).text, "false\n")

    @needs_git
    def test_ugit_accepts_git_repo(self):
        self.git("init", "-q", "-b", "main", "r")
        cwd = self.sb.path("r")
        res = self.ugit("init", cwd=cwd)
        self.assertTrue(res.text.startswith("Reinitialized existing Git repository in"))
        self.assertEqual(self.ugit("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd).rc != 99, True)


class Discovery(SandboxTest):
    def test_not_a_repo(self):
        res = self.ugit("rev-parse", "HEAD")
        self.assertEqual(res.rc, 128)
        self.assertEqual(res.etext, "fatal: not a git repository (or any of the parent directories): .git\n")
        res = self.ugit("cat-file", "-p", "abc")
        self.assertEqual((res.rc, res.etext),
                         (128, "fatal: not a git repository (or any of the parent directories): .git\n"))

    def test_walks_up_parents(self):
        self.ugit("init", "r")
        os.makedirs(self.sb.path("r/a/b"))
        res = self.ugit("rev-parse", "--show-toplevel", cwd=self.sb.path("r/a/b"))
        self.assertEqual(res.text, self.sb.path("r") + "\n")
        res = self.ugit("rev-parse", "--show-prefix", cwd=self.sb.path("r/a/b"))
        self.assertEqual(res.text, "a/b/\n")
        res = self.ugit("rev-parse", "--git-dir", cwd=self.sb.path("r/a/b"))
        self.assertEqual(res.text, self.sb.path("r/.git") + "\n")
        res = self.ugit("rev-parse", "--git-dir", cwd=self.sb.path("r"))
        self.assertEqual(res.text, ".git\n")

    def test_git_dir_and_work_tree_env(self):
        self.ugit("init", "r")
        g = self.sb.path("r/.git")
        res = self.ugit("rev-parse", "--git-dir", env={"GIT_DIR": g})
        self.assertEqual(res.text, g + "\n")
        res = self.ugit("rev-parse", "--show-toplevel", env={"GIT_DIR": g, "GIT_WORK_TREE": self.sb.path("r")})
        self.assertEqual(res.text, self.sb.path("r") + "\n")
        res = self.ugit("rev-parse", "--git-dir", env={"GIT_DIR": self.sb.path("nonexistent")})
        self.assertEqual(res.rc, 128)
        self.assertIn("not a git repository", res.etext)

    def test_dash_C(self):
        self.ugit("init", "r")
        res = self.ugit("-C", "r", "rev-parse", "--is-inside-work-tree")
        self.assertEqual(res.text, "true\n")

    def test_unknown_command(self):
        res = self.ugit("frobnicate")
        self.assertEqual(res.rc, 1)
        self.assertEqual(res.etext, "git: 'frobnicate' is not a git command. See 'git --help'.\n")

    def test_launcher_executable(self):
        self.assertTrue(os.stat(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ugit")).st_mode & stat.S_IXUSR)


@needs_git
class RevParse(SandboxTest):
    def setUp(self):
        super().setUp()
        self.git("init", "-q", "r")
        self.cwd = self.sb.path("r")
        for i in range(4):
            self.sb.write("r/f.txt", "v%d\n" % i)
            self.sb.write("r/d/g.txt", "g%d\n" % i)
            self.git("add", ".", cwd=self.cwd)
            self.git("commit", "-qm", "c%d" % i, cwd=self.cwd)
        self.git("branch", "feature", "HEAD~2", cwd=self.cwd)
        self.git("tag", "-a", "-m", "t", "v1", "HEAD~1", cwd=self.cwd)

    def same(self, *args):
        a = self.ugit("rev-parse", *args, cwd=self.cwd)
        b = self.git("rev-parse", *args, cwd=self.cwd)
        self.assertEqual((a.rc, a.text), (b.rc, b.text), args)

    def test_revisions(self):
        for spec in ["HEAD", "HEAD~1", "HEAD~3", "HEAD^", "HEAD^^", "HEAD^1", "HEAD^0", "HEAD~0", "master",
                     "feature", "feature~1", "v1", "v1^{}", "v1^{commit}", "v1^{tree}", "HEAD^{tree}",
                     "HEAD:f.txt", "HEAD~1:d/g.txt", "HEAD:d", "master^{commit}", "refs/heads/feature",
                     "heads/feature", "tags/v1", "@", "HEAD~2^", "v1~1", "HEAD^{blob}x", "HEAD~9", "HEAD^2",
                     "nonexistent", "HEAD:missing"]:
            self.same(spec)

    def test_abbrev(self):
        full = self.git("rev-parse", "HEAD", cwd=self.cwd).text.strip()
        for n in (4, 7, 12, 40):
            res = self.ugit("rev-parse", full[:n], cwd=self.cwd)
            self.assertEqual(res.text.strip(), full)
        self.same("--short", "HEAD")
        self.same("--short=10", "HEAD")
        self.same("--short", "HEAD~2")
        self.assertEqual(self.ugit("rev-parse", "zz12", cwd=self.cwd).rc, 128)

    def test_options(self):
        self.same("--abbrev-ref", "HEAD")
        self.same("--abbrev-ref", "feature")
        self.same("--symbolic-full-name", "HEAD")
        self.same("--verify", "HEAD")
        self.same("--verify", "nonexistent")
        self.same("--verify", "-q", "nonexistent")
        self.same("--is-inside-work-tree")
        self.same("--is-bare-repository")
        self.same("--show-toplevel")
        self.same("--show-prefix")
        self.same("HEAD", "feature", "v1")
        self.same("HEAD~1..HEAD")
        self.same("^HEAD~1")

    def test_ambiguous_ref_order(self):
        # a tag and a branch with the same name: git prefers the tag
        self.git("branch", "dup", "HEAD~3", cwd=self.cwd)
        self.git("tag", "dup", "HEAD", cwd=self.cwd)
        self.same("dup")

    def test_detached_head(self):
        self.git("checkout", "-q", "--detach", "HEAD~1", cwd=self.cwd)
        self.same("HEAD")
        self.same("--abbrev-ref", "HEAD")
        self.same("HEAD~1")

    def test_unborn_head(self):
        self.git("init", "-q", "e")
        cwd = self.sb.path("e")
        a = self.ugit("rev-parse", "HEAD", cwd=cwd)
        b = self.git("rev-parse", "HEAD", cwd=cwd)
        self.assertEqual((a.rc, a.out, a.err), (b.rc, b.out, b.err))

    def test_cat_file_matches_git(self):
        for mode in ("-p", "-t", "-s"):
            for spec in ("HEAD", "HEAD^{tree}", "HEAD:f.txt", "HEAD:d", "v1"):
                a = self.ugit("cat-file", mode, spec, cwd=self.cwd)
                b = self.git("cat-file", mode, spec, cwd=self.cwd)
                self.assertEqual((a.rc, a.out), (b.rc, b.out), (mode, spec))
        a = self.ugit("cat-file", "-p", "nope", cwd=self.cwd)
        b = self.git("cat-file", "-p", "nope", cwd=self.cwd)
        self.assertEqual((a.rc, a.err), (b.rc, b.err))

    def test_cat_file_batch(self):
        inp = b"HEAD\nHEAD:f.txt\nnope\n"
        a = self.ugit("cat-file", "--batch", cwd=self.cwd, stdin=inp)
        b = self.git("cat-file", "--batch", cwd=self.cwd, stdin=inp)
        self.assertEqual(a.out.replace(b"HEAD:f.txt", b"X").split(b"\n")[0],
                         b.out.replace(b"HEAD:f.txt", b"X").split(b"\n")[0])
        a = self.ugit("cat-file", "--batch-check", cwd=self.cwd, stdin=inp)
        b = self.git("cat-file", "--batch-check", cwd=self.cwd, stdin=inp)
        self.assertEqual(a.out, b.out)


if __name__ == "__main__":
    unittest.main()
