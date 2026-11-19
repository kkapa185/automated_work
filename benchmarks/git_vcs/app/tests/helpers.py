"""Test helpers: run ugit / real git in temporary repositories."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UGIT = os.path.join(ROOT, "ugit")
HAVE_GIT = shutil.which("git") is not None
needs_git = unittest.skipUnless(HAVE_GIT, "real git not available")


class Result:
    def __init__(self, cp):
        self.rc = cp.returncode
        self.out = cp.stdout
        self.err = cp.stderr

    @property
    def text(self):
        return self.out.decode("utf-8", "replace")

    @property
    def etext(self):
        return self.err.decode("utf-8", "replace")


class Sandbox:
    """A temp dir with a private HOME and deterministic identity environment."""

    def __init__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="ugit-test-"))
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self.work = os.path.join(self.root, "work")
        os.makedirs(self.work)
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.home,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test Author",
            "GIT_AUTHOR_EMAIL": "author@example.com",
            "GIT_AUTHOR_DATE": "@1700000000 +0000",
            "GIT_COMMITTER_NAME": "Test Committer",
            "GIT_COMMITTER_EMAIL": "committer@example.com",
            "GIT_COMMITTER_DATE": "@1700000000 +0000",
            "TZ": "UTC",
            "LC_ALL": "C",
        }

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def path(self, *p):
        return os.path.join(self.work, *p)

    def write(self, name, content, mode=None):
        p = self.path(name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(content if isinstance(content, bytes) else content.encode())
        if mode:
            os.chmod(p, mode)
        return p

    def _run(self, argv, cwd=None, env=None, stdin=None):
        e = dict(self.env)
        e.update(env or {})
        cp = subprocess.run(argv, cwd=cwd or self.work, env=e, input=stdin,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return Result(cp)

    def ugit(self, *args, cwd=None, env=None, stdin=None):
        return self._run([sys.executable, UGIT] + list(args), cwd, env, stdin)

    def git(self, *args, cwd=None, env=None, stdin=None):
        return self._run(["git"] + list(args), cwd, env, stdin)


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)

    def ugit(self, *a, **k):
        return self.sb.ugit(*a, **k)

    def git(self, *a, **k):
        return self.sb.git(*a, **k)


def sha1_object(typ, body):
    """Independent reference implementation of the git object id definition."""
    return hashlib.sha1(("%s %d" % (typ, len(body))).encode() + b"\0" + body).hexdigest()


def loose_bytes(typ, body):
    return zlib.compress(("%s %d" % (typ, len(body))).encode() + b"\0" + body)


class PairTest(SandboxTest):
    """Two identical repositories: 'g' driven by real git and 'u' driven by ugit."""

    init_repos = True

    def setUp(self):
        super().setUp()
        self.dirs = {"g": self.sb.path("g"), "u": self.sb.path("u")}
        if self.init_repos:
            self.git("init", "-q", "g")
            self.ugit("init", "-q", "u")

    def put(self, name, content="x\n", mode=None):
        for d in self.dirs.values():
            p = os.path.join(d, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(content if isinstance(content, bytes) else content.encode())
            if mode:
                os.chmod(p, mode)

    def both(self, *args, sub="", stdin=None, env=None, git_args=None):
        """Run the same command with both tools; assert identical stdout/stderr/exit code."""
        g = self.git(*(git_args or args), cwd=os.path.join(self.dirs["g"], sub), stdin=stdin, env=env)
        u = self.ugit(*args, cwd=os.path.join(self.dirs["u"], sub), stdin=stdin, env=env)
        msg = "args=%r\n--git out=%r err=%r rc=%d\n--ugit out=%r err=%r rc=%d" % (
            args, g.text, g.etext, g.rc, u.text, u.etext, u.rc)
        self.assertEqual(g.rc, u.rc, msg)
        self.assertEqual(g.text, u.text, msg)
        ge, ue = g.etext.replace(self.dirs["g"], "R"), u.etext.replace(self.dirs["u"], "R")
        if g.rc == 129:  # usage text itself is not part of the contract; "error: ..." lines are
            ge, ue = ge.split("\n")[0], ue.split("\n")[0]
            if ge.startswith("usage:") and ue.startswith("usage:"):
                ge = ue = "usage:"
        self.assertEqual(ge, ue, msg)
        return u

    def both_git(self, *args, **kw):
        """Run with real git in both repos (setup that ugit cannot do yet)."""
        for d in self.dirs.values():
            r = self.git(*args, cwd=os.path.join(d, kw.get("sub", "")), env=kw.get("env"))
            self.assertEqual(r.rc, 0, (args, r.etext))

    def same_objects(self):
        """HEAD ids must be identical (same tree, same commit bytes)."""
        g = self.git("rev-parse", "HEAD", cwd=self.dirs["g"])
        u = self.git("rev-parse", "HEAD", cwd=self.dirs["u"])
        self.assertEqual(g.text, u.text)
        self.assertEqual(self.git("fsck", "--strict", cwd=self.dirs["u"]).rc, 0)
