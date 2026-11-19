"""git init"""
import os

from ..refs import check_refname_format
from ..repo import is_gitdir
from ..util import Fatal, out, usage_error, unknown_opt_msg

USAGE = "git init [-q | --quiet] [--bare] [-b <branch-name> | --initial-branch=<branch-name>] [<directory>]"

INFO_EXCLUDE = """# git ls-files --others --exclude-from=.git/info/exclude
# Lines that start with '#' are comments.
# For a project mostly in C, the following would be a good set of
# exclude patterns (uncomment them if you want to use them):
# *.[oa]
# *~
"""


def _filemode_supported(gitdir):
    probe = os.path.join(gitdir, "ugit_filemode_probe")
    try:
        with open(probe, "w"):
            pass
        os.chmod(probe, 0o644)
        before = os.stat(probe).st_mode & 0o111
        os.chmod(probe, 0o755)
        after = os.stat(probe).st_mode & 0o111
        return before != after
    except OSError:
        return True
    finally:
        try:
            os.unlink(probe)
        except OSError:
            pass


def run(ctx, args):
    branch = None
    bare = False
    quiet = False
    directory = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-b", "--initial-branch"):
            if i + 1 >= len(args):
                usage_error("switch `b' requires a value", USAGE)
            branch = args[i + 1]
            i += 1
        elif a.startswith("--initial-branch="):
            branch = a.split("=", 1)[1]
        elif a == "--bare":
            bare = True
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a.startswith("--template") or a == "--shared":
            if a == "--template":
                i += 1
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            if directory is not None:
                usage_error("too many arguments", USAGE)
            directory = a
        i += 1
    if branch is not None and not check_refname_format("refs/heads/" + branch):
        raise Fatal("invalid initial branch name: '%s'" % branch)
    if branch is None:
        branch = "master"

    if directory is not None:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as e:
            raise Fatal("cannot mkdir %s: %s" % (directory, e.strerror))
        os.chdir(directory)
    cwd = os.getcwd()
    if ctx.env.get("GIT_DIR"):
        gitdir = os.path.abspath(os.path.join(cwd if directory is None else cwd, ctx.env["GIT_DIR"]))
        if directory is None:
            gitdir = os.path.abspath(ctx.env["GIT_DIR"])
    elif bare:
        gitdir = cwd
    else:
        gitdir = os.path.join(cwd, ".git")

    reinit = is_gitdir(gitdir)
    for d in ("", "objects", "objects/info", "objects/pack", "refs", "refs/heads", "refs/tags",
              "info", "hooks", "branches"):
        os.makedirs(os.path.join(gitdir, d), exist_ok=True)
    head = os.path.join(gitdir, "HEAD")
    if not os.path.exists(head):
        with open(head, "w") as f:
            f.write("ref: refs/heads/%s\n" % branch)
    cfg = os.path.join(gitdir, "config")
    if not os.path.exists(cfg):
        filemode = "true" if _filemode_supported(gitdir) else "false"
        text = "[core]\n\trepositoryformatversion = 0\n\tfilemode = %s\n\tbare = %s\n" % (
            filemode, "true" if bare else "false")
        if not bare:
            text += "\tlogallrefupdates = true\n"
        with open(cfg, "w") as f:
            f.write(text)
    desc = os.path.join(gitdir, "description")
    if not os.path.exists(desc):
        with open(desc, "w") as f:
            f.write("Unnamed repository; edit this file 'description' to name the repository.\n")
    exclude = os.path.join(gitdir, "info", "exclude")
    if not os.path.exists(exclude):
        with open(exclude, "w") as f:
            f.write(INFO_EXCLUDE)
    if not quiet:
        out("%s Git repository in %s/\n" % (
            "Reinitialized existing" if reinit else "Initialized empty", gitdir.rstrip("/")))
    return 0
