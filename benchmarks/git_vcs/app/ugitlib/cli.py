"""Command-line entry point and dispatcher."""
import importlib
import os
import sys

from .objects import CorruptObject, ObjectNotFound
from .util import Exit, Fatal, err
from . import repo as repomod


class Context:
    def __init__(self, env=None):
        self.env = dict(os.environ) if env is None else env
        self.cwd = os.getcwd()
        self._repo = None
        self.config_overrides = []

    def repo(self):
        if self._repo is None:
            self._repo = repomod.discover(self.cwd, self.env)
            self._repo.config.overrides.extend(self.config_overrides)
        return self._repo

    def worktree_repo(self):
        r = self.repo()
        if r.worktree is None:
            raise Fatal("this operation must be run in a work tree")
        return r

    def try_repo(self):
        try:
            return self.repo()
        except Fatal:
            return None


def main(argv):
    ctx = Context()
    args = list(argv)
    try:
        while args and args[0].startswith("-") and args[0] != "-":
            a = args[0]
            if a == "-C" and len(args) > 1:
                os.chdir(os.path.join(os.getcwd(), args[1]))
                ctx.cwd = os.getcwd()
                del args[:2]
            elif a == "-c" and len(args) > 1:
                k, _, v = args[1].partition("=")
                ctx.config_overrides.append((k.lower() if "." not in k else _norm(k), v))
                del args[:2]
            elif a.startswith("--git-dir="):
                ctx.env["GIT_DIR"] = a.split("=", 1)[1]
                del args[0]
            elif a.startswith("--work-tree="):
                ctx.env["GIT_WORK_TREE"] = a.split("=", 1)[1]
                del args[0]
            elif a in ("--version", "version"):
                from . import __version__
                sys.stdout.write("git version 2.43.0 (ugit %s)\n" % __version__)
                return 0
            elif a == "--no-pager" or a == "-P":
                del args[0]
            else:
                break
        if not args:
            sys.stdout.write("usage: git [-C <path>] [-c <name>=<value>] <command> [<args>]\n")
            return 1
        name = args[0]
        modname = name.replace("-", "_")
        try:
            if not modname.isidentifier():
                raise ImportError
            mod = importlib.import_module("ugitlib.commands." + modname)
        except ImportError:
            err("git: '%s' is not a git command. See 'git --help'.\n" % name)
            return 1
        rc = mod.run(ctx, args[1:])
        sys.stdout.flush()
        return rc or 0
    except Fatal as e:
        sys.stdout.flush()
        err(("%s%s\n" % (e.prefix, e.msg)))
        return e.code
    except Exit as e:
        sys.stdout.flush()
        return e.code
    except ObjectNotFound as e:
        sys.stdout.flush()
        err("fatal: bad object %s\n" % (e.args[0] if e.args else ""))
        return 128
    except CorruptObject as e:
        sys.stdout.flush()
        err("fatal: %s\n" % e)
        return 128
    except BrokenPipeError:
        try:
            sys.stdout = None
        except Exception:
            pass
        os._exit(141)
    except KeyboardInterrupt:
        return 130
    except OSError as e:
        sys.stdout.flush()
        err("fatal: %s%s\n" % (e.strerror or e, " '%s'" % e.filename if e.filename else ""))
        return 128
    except Exception as e:  # last resort: never show a traceback to the user
        try:
            sys.stdout.flush()
        except Exception:
            pass
        err("fatal: internal error: %s: %s\n" % (type(e).__name__, e))
        if os.environ.get("UGIT_DEBUG"):
            raise
        return 128


def _norm(key):
    from .config import parse_key, canonical_key
    try:
        return canonical_key(*parse_key(key))
    except ValueError:
        return key
