import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import SandboxTest, needs_git  # noqa: E402
from ugitlib.ident import parse_date, format_date, format_tz  # noqa: E402
from ugitlib.config import ConfigFile, parse_key  # noqa: E402


class Dates(unittest.TestCase):
    def test_raw_with_at(self):
        self.assertEqual(parse_date("@1700000000 +0000"), (1700000000, 0))

    def test_raw_plain(self):
        self.assertEqual(parse_date("1700000000 +0000"), (1700000000, 0))

    def test_raw_with_offset(self):
        self.assertEqual(parse_date("1700000000 -0530"), (1700000000, -330))
        self.assertEqual(format_tz(-330), "-0530")

    def test_iso(self):
        self.assertEqual(parse_date("2023-11-14T22:13:20 +0000"), (1700000000, 0))
        self.assertEqual(parse_date("2023-11-14 23:13:20 +0100"), (1700000000, 60))
        self.assertEqual(parse_date("2023-11-14T22:13:20Z"), (1700000000, 0))

    def test_rfc2822(self):
        self.assertEqual(parse_date("Tue, 14 Nov 2023 22:13:20 +0000"), (1700000000, 0))

    def test_format(self):
        # 2023-11-14 was a Tuesday
        self.assertEqual(format_date(1700000000, 0), "Tue Nov 14 22:13:20 2023 +0000")
        self.assertEqual(format_date(1700000000, 120), "Wed Nov 15 00:13:20 2023 +0200")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_date("not a date")


class ConfigParsing(SandboxTest):
    def test_parse_variants(self):
        p = self.sb.write("cfg", '# c\n[Core]\n\tBare = false\n[remote "Origin"]\n\turl = a b ; cmt\n'
                                 '\tq = "  x # y "\n\tflag\n[a.b]\n k = 1\n')
        c = ConfigFile(p)
        d = dict(c.items())
        self.assertEqual(d["core.bare"], "false")
        self.assertEqual(d["remote.Origin.url"], "a b")
        self.assertEqual(d["remote.Origin.q"], "  x # y ")
        self.assertIsNone(d["remote.Origin.flag"])
        self.assertEqual(d["a.b.k"], "1")

    def test_parse_key(self):
        self.assertEqual(parse_key("Remote.Foo.Bar.URL"), ("remote", "Foo.Bar", "url"))
        with self.assertRaises(ValueError):
            parse_key("nodots")

    def test_cli_get_set_unset(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.assertEqual(self.ugit("config", "--get", "user.name", cwd=cwd).rc, 1)
        self.assertEqual(self.ugit("config", "user.name", "Ann Lee", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("config", "user.name", cwd=cwd).text, "Ann Lee\n")
        self.assertEqual(self.ugit("config", "--get", "USER.NAME", cwd=cwd).text, "Ann Lee\n")
        self.ugit("config", "user.email", "ann@x.org", cwd=cwd)
        self.ugit("config", "branch.dev.remote", "origin", cwd=cwd)
        text = open(os.path.join(cwd, ".git/config")).read()
        self.assertIn('[user]\n\tname = Ann Lee\n\temail = ann@x.org\n', text)
        self.assertIn('[branch "dev"]\n\tremote = origin\n', text)
        self.ugit("config", "user.name", "Bob", cwd=cwd)
        self.assertEqual(self.ugit("config", "user.name", cwd=cwd).text, "Bob\n")
        self.assertEqual(self.ugit("config", "--unset", "user.name", cwd=cwd).rc, 0)
        self.assertEqual(self.ugit("config", "--get", "user.name", cwd=cwd).rc, 1)
        lst = self.ugit("config", "--list", cwd=cwd).text
        self.assertIn("core.bare=false\n", lst)
        self.assertIn("user.email=ann@x.org\n", lst)

    def test_invalid_key(self):
        self.ugit("init", "r")
        res = self.ugit("config", "foo", cwd=self.sb.path("r"))
        self.assertEqual(res.rc, 1)
        self.assertIn("key does not contain a section", res.etext)

    @needs_git
    def test_interop_with_git(self):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.ugit("config", "user.name", "Zed Q", cwd=cwd)
        self.ugit("config", "remote.origin.url", "https://example.com/x.git", cwd=cwd)
        self.assertEqual(self.git("config", "user.name", cwd=cwd).text, "Zed Q\n")
        self.assertEqual(self.git("config", "remote.origin.url", cwd=cwd).text, "https://example.com/x.git\n")
        self.git("config", "core.editor", "vi me", cwd=cwd)
        self.assertEqual(self.ugit("config", "core.editor", cwd=cwd).text, "vi me\n")
        self.git("config", "a.b", "has # hash", cwd=cwd)
        self.assertEqual(self.ugit("config", "a.b", cwd=cwd).text, "has # hash\n")
        self.ugit("config", "a.c", " lead;semi", cwd=cwd)
        self.assertEqual(self.git("config", "a.c", cwd=cwd).text, " lead;semi\n")

    def test_global_config_read(self):
        open(os.path.join(self.sb.home, ".gitconfig"), "w").write("[user]\n\tname = Global G\n")
        self.ugit("init", "r")
        self.assertEqual(self.ugit("config", "user.name", cwd=self.sb.path("r")).text, "Global G\n")


class Environment(SandboxTest):
    """GIT_* variables are honoured when producing identities."""

    def ident(self, env=None, setup=None):
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return cwd

    def test_ident_from_env_and_config(self):
        from ugitlib.ident import get_ident
        from ugitlib.config import Config
        self.ugit("init", "r")
        cwd = self.sb.path("r")
        self.ugit("config", "user.name", "Cfg Name", cwd=cwd)
        self.ugit("config", "user.email", "cfg@x", cwd=cwd)
        cfg = Config(os.path.join(cwd, ".git"), {"HOME": self.sb.home, "GIT_CONFIG_NOSYSTEM": "1"})
        env = {"GIT_AUTHOR_DATE": "@1700000000 +0100"}
        self.assertEqual(get_ident("AUTHOR", cfg, env), "Cfg Name <cfg@x> 1700000000 +0100")
        env = {"GIT_COMMITTER_NAME": "Env C", "GIT_COMMITTER_EMAIL": "e@c", "GIT_COMMITTER_DATE": "1700000000 +0000"}
        self.assertEqual(get_ident("COMMITTER", cfg, env), "Env C <e@c> 1700000000 +0000")

    def test_unknown_identity(self):
        from ugitlib.ident import get_ident
        from ugitlib.config import Config
        from ugitlib.util import Fatal
        cfg = Config(None, {"HOME": self.sb.home, "GIT_CONFIG_NOSYSTEM": "1"})
        with self.assertRaises(Fatal) as cm:
            get_ident("AUTHOR", cfg, {})
        self.assertIn("Author identity unknown", cm.exception.msg)
        self.assertEqual(cm.exception.code, 128)

    def test_invalid_date(self):
        from ugitlib.ident import get_ident
        from ugitlib.config import Config
        from ugitlib.util import Fatal
        cfg = Config(None, {"HOME": self.sb.home, "GIT_CONFIG_NOSYSTEM": "1"})
        with self.assertRaises(Fatal):
            get_ident("AUTHOR", cfg, {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "b", "GIT_AUTHOR_DATE": "garbage"})


if __name__ == "__main__":
    unittest.main()
