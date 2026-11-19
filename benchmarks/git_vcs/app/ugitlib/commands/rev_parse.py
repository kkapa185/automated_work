"""git rev-parse"""
import os

from ..objects import ObjectNotFound
from ..repo import BadRevision
from ..util import Exit, Fatal, out, err


def _bad_arg(arg):
    return Fatal("ambiguous argument '%s': unknown revision or path not in the working tree.\n"
                 "Use '--' to separate paths from revisions, like this:\n"
                 "'git <command> [<revision>...] -- [<file>...]'" % arg)


def run(ctx, args):
    verify = quiet = False
    short = None
    abbrev_ref = False
    symbolic_full = False
    default = None
    items = []
    i = 0
    dashdash = False
    while i < len(args):
        a = args[i]
        if dashdash:
            items.append(("path", a))
        elif a == "--":
            dashdash = True
            items.append(("raw", "--"))
        elif a == "--verify":
            verify = True
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a == "--short":
            short = 0
        elif a.startswith("--short="):
            short = int(a.split("=", 1)[1])
        elif a.startswith("--abbrev-ref"):
            abbrev_ref = True
        elif a == "--symbolic-full-name":
            symbolic_full = True
        elif a == "--default":
            i += 1
            default = args[i]
        elif a in ("--git-dir", "--show-toplevel", "--is-inside-work-tree", "--is-bare-repository",
                   "--show-prefix", "--show-cdup", "--is-inside-git-dir", "--absolute-git-dir",
                   "--git-common-dir", "--show-object-format"):
            items.append(("opt", a))
        elif a in ("--sq", "--revs-only", "--no-flags", "--flags", "--symbolic", "--not"):
            pass
        elif a.startswith("-") and a != "-":
            items.append(("raw", a))
        else:
            items.append(("rev", a))
        i += 1
    if default is not None and not any(k == "rev" for k, _ in items):
        items.append(("rev", default))
    repo = ctx.repo() if any(k == "opt" or k == "rev" for k, _ in items) else None
    if verify:
        revs = [v for k, v in items if k == "rev"]
        if len(revs) != 1:
            if quiet:
                return 1
            raise Fatal("Needed a single revision")
        try:
            sha = repo.resolve(revs[0])
            if not repo.odb.exists(sha):
                raise BadRevision(revs[0])
        except BadRevision:
            if quiet:
                return 1
            raise Fatal("Needed a single revision")
        out((repo.odb.shorten(sha, short or None) if short is not None else sha) + "\n")
        return 0
    for kind, v in items:
        if kind == "opt":
            out(_option(repo, ctx, v))
        elif kind == "raw":
            out(v + "\n")
        elif kind == "path":
            out(v + "\n")
        else:
            _show_rev(repo, v, short, abbrev_ref, symbolic_full)
    return 0


def _option(repo, ctx, opt):
    if opt == "--git-dir":
        gd = repo.gitdir
        if ctx.env.get("GIT_DIR"):
            return ctx.env["GIT_DIR"] + "\n"
        if repo.worktree and os.path.join(repo.worktree, ".git") == gd and ctx.cwd == repo.worktree:
            return ".git\n"
        return gd + "\n"
    if opt == "--absolute-git-dir" or opt == "--git-common-dir":
        return (repo.gitdir if opt == "--absolute-git-dir" else
                (".git" if ctx.cwd == repo.worktree else repo.gitdir)) + "\n"
    if opt == "--show-toplevel":
        if repo.worktree is None:
            raise Fatal("this operation must be run in a work tree")
        return repo.worktree + "\n"
    if opt == "--is-inside-work-tree":
        return "false\n" if repo.worktree is None or _inside(ctx.cwd, repo.gitdir) else "true\n"
    if opt == "--is-bare-repository":
        return "true\n" if repo.worktree is None else "false\n"
    if opt == "--is-inside-git-dir":
        return "true\n" if _inside(ctx.cwd, repo.gitdir) else "false\n"
    if opt == "--show-prefix":
        return repo.prefix + "\n"
    if opt == "--show-cdup":
        return "../" * (repo.prefix.count("/")) + "\n"
    if opt == "--show-object-format":
        return "sha1\n"
    return ""


def _inside(path, d):
    return path == d or path.startswith(d.rstrip("/") + "/")


def _show_rev(repo, arg, short, abbrev_ref, symbolic_full):
    if arg.startswith("^") and len(arg) > 1:
        try:
            out("^" + repo.resolve(arg[1:]) + "\n")
            return
        except BadRevision:
            pass
    if ".." in arg and "..." not in arg:
        a, _, b = arg.partition("..")
        try:
            sa = repo.resolve_commit(a or "HEAD")
            sb = repo.resolve_commit(b or "HEAD")
            out(sb + "\n^" + sa + "\n")
            return
        except BadRevision:
            pass
    try:
        sha = repo.resolve(arg)
        if not repo.odb.exists(sha):
            raise BadRevision(arg)
    except BadRevision as e:
        if e.ambiguous:
            err("error: short object ID %s is ambiguous\n" % arg)
        out(arg + "\n")
        raise _bad_arg(arg)
    if abbrev_ref or symbolic_full:
        base = arg.split("^")[0].split("~")[0]
        full = repo.dwim_ref(base or "HEAD")
        if full is None:
            out(arg + "\n")
            raise _bad_arg(arg)
        if full == "HEAD" or (symbolic_full and not abbrev_ref):
            target = repo.refs.symref_target(full) if full == "HEAD" else None
            if symbolic_full:
                out((target or full) + "\n")
                return
            out((target[len("refs/heads/"):] if target and target.startswith("refs/heads/")
                 else (target or "HEAD")) + "\n")
            return
        final = repo.refs.final_ref(full)
        for pfx in ("refs/heads/", "refs/remotes/", "refs/tags/"):
            if final.startswith(pfx):
                name = final[len(pfx):]
                if pfx == "refs/tags/" and (repo.refs.resolve("refs/heads/" + name)):
                    name = "tags/" + name
                out(name + "\n")
                return
        out(final + "\n")
        return
    if short is not None:
        out(repo.odb.shorten(sha, short or None) + "\n")
    else:
        out(sha + "\n")
