"""Randomised differential test: the same random sequence of porcelain commands is run with real git
and with ugit; every command's stdout/stderr/exit status and the resulting repository state must agree."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import PairTest, needs_git  # noqa: E402
from test_switching import StateMixin  # noqa: E402

PATHS = ["a.txt", "b.txt", "c.txt", "d/e.txt", "d/f.txt", "d/g/h.txt", "run.sh", "z"]
# merge does no rename detection (documented), so keep file contents distinct enough that git does not
# see accidental renames, and do not generate `mv`.
VOCAB = ["alpha", "beta", "gamma", "delta", "", "  indented", "}", "x = 1"]


@needs_git
class WorkflowFuzz(StateMixin, PairTest):
    def run_seed(self, seed, steps=45):
        rnd = random.Random(seed)
        t = [1700000000]
        branches = ["master"]
        conflicted = False

        def env():
            t[0] += 60
            return {"GIT_AUTHOR_DATE": "@%d +0000" % t[0], "GIT_COMMITTER_DATE": "@%d +0000" % t[0]}

        def tracked():
            return self.git("ls-files", cwd=self.dirs["g"]).text.split()

        def pick_path():
            return rnd.choice(PATHS)

        def content(path=None):
            body = "".join(rnd.choice(VOCAB) + "\n" for _ in range(rnd.randint(1, 8)))
            return "# %s\n%s" % (path, body)

        log = []
        for step in range(steps):
            op = rnd.choice(["write", "write", "write", "add", "add", "commit", "commit", "rm", "branch",
                             "checkout", "checkout", "merge", "merge", "reset", "restore", "tag", "delete",
                             "checkout_path", "status", "diff", "log", "amend", "chmod"])
            cmd = None
            if op == "write":
                p = pick_path()
                self.put(p, content(p))
                log.append(("write", p))
                continue
            if op == "delete":
                p = pick_path()
                for d in self.dirs.values():
                    fp = os.path.join(d, p)
                    if os.path.exists(fp):
                        os.unlink(fp)
                log.append(("delete", p))
                continue
            if op == "chmod":
                p = pick_path()
                for d in self.dirs.values():
                    fp = os.path.join(d, p)
                    if os.path.exists(fp) and not os.path.islink(fp):
                        os.chmod(fp, 0o755 if not os.access(fp, os.X_OK) else 0o644)
                log.append(("chmod", p))
                continue
            if op == "add":
                cmd = ["add"] + rnd.choice([["."], ["-A"], [pick_path()], ["-u"], [pick_path(), pick_path()]])
            elif op == "commit":
                cmd = ["commit"] + rnd.choice([["-m", "c%d" % step], ["-a", "-m", "c%d" % step],
                                               ["--allow-empty", "-m", "e%d" % step]])
            elif op == "amend":
                cmd = ["commit", "--amend", "-m", "amended %d" % step]
            elif op == "rm":
                ts = tracked()
                cmd = ["rm"] + rnd.choice([[], ["--cached"], ["-f"]]) + [rnd.choice(ts) if ts else pick_path()]
            elif op == "mv":
                ts = tracked()
                cmd = ["mv", rnd.choice(ts) if ts else pick_path(), rnd.choice(["m1.txt", "dd/m2.txt", "d/m3.txt"])]
            elif op == "branch":
                name = "br%d" % rnd.randint(0, 3)
                cmd = rnd.choice([["branch", name], ["branch", "-d", name], ["branch", "-D", name], ["branch"]])
            elif op == "checkout":
                name = rnd.choice(["master", "br0", "br1", "br2", "br3", "HEAD~1", "HEAD~2"])
                cmd = rnd.choice([["checkout", name], ["switch", name], ["checkout", "-b", "nb%d" % rnd.randint(0, 3)],
                                  ["switch", "-c", "ns%d" % rnd.randint(0, 3)], ["checkout", "-f", name],
                                  ["switch", "--detach", name]])
            elif op == "merge":
                name = rnd.choice(["master", "br0", "br1", "br2", "br3", "nb0", "nb1", "ns0"])
                cmd = ["merge"] + rnd.choice([[name], [name], ["--no-ff", name], ["--abort"], ["--ff-only", name],
                                              ["--no-commit", name]])
            elif op == "reset":
                cmd = ["reset"] + rnd.choice([["--soft", "HEAD~1"], ["--mixed", "HEAD~1"], ["--hard", "HEAD~1"],
                                              ["--hard"], [], [pick_path()], ["--hard", "master"]])
            elif op == "restore":
                cmd = ["restore"] + rnd.choice([[pick_path()], ["--staged", pick_path()], ["."],
                                                ["--source=HEAD~1", pick_path()], ["-S", "-W", pick_path()]])
            elif op == "tag":
                cmd = rnd.choice([["tag", "t%d" % rnd.randint(0, 3)], ["tag", "-a", "-m", "m", "at%d" % rnd.randint(0, 2)],
                                  ["tag"], ["tag", "-d", "t%d" % rnd.randint(0, 3)]])
            elif op == "checkout_path":
                cmd = ["checkout"] + rnd.choice([["--", pick_path()], ["HEAD~1", "--", pick_path()], ["--", "."]])
            elif op == "status":
                cmd = rnd.choice([["status"], ["status", "-s"], ["status", "--porcelain", "-b"]])
            elif op == "diff":
                cmd = ["diff"] + rnd.choice([[], ["--cached"], ["HEAD"], ["--stat"], ["--name-status", "HEAD"]])
            else:
                cmd = rnd.choice([["log", "--oneline", "--all"], ["log", "-3"], ["show", "--stat"], ["ls-files", "-s"],
                                  ["log", "--format=%h %p %s", "--first-parent"]])
            e = env()
            g = self.git(*cmd, cwd=self.dirs["g"], env=e)
            u = self.ugit(*cmd, cwd=self.dirs["u"], env=e)
            msg = "seed=%d step=%d cmd=%r\nhistory=%r\n--git rc=%d out=%r err=%r\n--ugit rc=%d out=%r err=%r" % (
                seed, step, cmd, log[-12:], g.rc, g.text, g.etext, u.rc, u.text, u.etext)
            self.assertEqual(g.rc, u.rc, msg)
            self.assertEqual(g.text, u.text, msg)
            ge = g.etext.replace(self.dirs["g"], "R")
            ue = u.etext.replace(self.dirs["u"], "R")
            if g.rc == 129:
                ge, ue = ge.split("\n")[0], ue.split("\n")[0]
            self.assertEqual(ge, ue, msg)
            log.append(tuple(cmd))
            try:
                self.same_state()
            except AssertionError as ex:
                raise AssertionError("%s\n%s" % (msg, ex))
            if not g.rc and cmd[0] in ("checkout", "switch", "commit") and step % 7 == 0:
                pass

    def seed_repo(self):
        for p in PATHS[:4]:
            self.put(p, "".join("%s line %d\n" % (p, i) for i in range(6)))
        self.both("add", ".", env={"GIT_AUTHOR_DATE": "@1700000000 +0000", "GIT_COMMITTER_DATE": "@1700000000 +0000"})
        self.both("commit", "-m", "initial", env={"GIT_AUTHOR_DATE": "@1700000001 +0000",
                                                  "GIT_COMMITTER_DATE": "@1700000001 +0000"})

    def test_extra_seeds_from_environment(self):
        """FUZZ_SEEDS=10:40 (and optionally FUZZ_STEPS) runs more random sequences."""
        spec = os.environ.get("FUZZ_SEEDS")
        if not spec:
            self.skipTest("set FUZZ_SEEDS=a:b to run more seeds")
        lo, hi = (int(x) for x in spec.split(":"))
        for seed in range(lo, hi):
            self.setUp()
            self.seed_repo()
            self.run_seed(seed, int(os.environ.get("FUZZ_STEPS", "45")))
            self.sb.cleanup()

    def test_seeds_0_to_4(self):
        for seed in range(5):
            self.setUp()
            self.seed_repo()
            self.run_seed(seed)
            self.sb.cleanup()

    def test_seeds_5_to_9(self):
        for seed in range(5, 10):
            self.setUp()
            self.seed_repo()
            self.run_seed(seed)
            self.sb.cleanup()


if __name__ == "__main__":
    unittest.main()
