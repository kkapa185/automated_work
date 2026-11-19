"""git switch"""
from ..objects import ObjectNotFound
from ..refs import check_refname_format
from ..repo import BadRevision
from ..util import Fatal, err, expand_short, usage_error, unknown_opt_msg
from . import checkout as CO

USAGE = "git switch [<options>] [<branch>]"


def run(ctx, args):
    args = expand_short(args, "fq", "cC")
    create = None
    force_create = False
    force = quiet = detach = False
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-c", "--create", "-C", "--force-create"):
            i += 1
            if i >= len(args):
                usage_error("switch `%s' requires a value" % a.lstrip("-")[:1], USAGE)
            create = args[i]
            force_create = a in ("-C", "--force-create")
        elif a in ("-f", "--force", "--discard-changes"):
            force = True
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a in ("-d", "--detach"):
            detach = True
        elif a in ("--no-guess", "--guess", "--no-track", "-t", "--track", "--progress", "--no-progress"):
            pass
        elif a == "--":
            pos += args[i + 1:]
            break
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
        i += 1
    repo = ctx.worktree_repo()
    if create is not None:
        if len(pos) > 1:
            raise Fatal(USAGE, 129, prefix="usage: ")
        return CO.do_create(ctx, repo, create, pos[0] if pos else None, force_create, force, quiet,
                            switch_style=True)
    if not pos and detach:
        return CO.do_detach(ctx, repo, "HEAD", force, quiet, True)
    if len(pos) != 1:
        if not pos:
            raise Fatal("missing branch or commit argument")
        raise Fatal(USAGE, 129, prefix="usage: ")
    name = pos[0]
    if name == "-":
        from .. import reflog
        name = reflog.previous_checkout(repo)
        if name is None:
            raise Fatal("invalid reference: @{-1}")
        if len(name) == 40 and repo.refs.resolve("refs/heads/" + name) is None:
            detach = True
    if detach:
        return CO.do_detach(ctx, repo, name, force, quiet, True)
    if repo.refs.resolve("refs/heads/" + name) is not None:
        return CO.do_branch_switch(ctx, repo, name, force, quiet)
    try:
        sha = repo.resolve(name)
        if repo.odb.exists(sha):
            typ = repo.odb.read(sha)[0]
            err("hint: If you want to detach HEAD at the commit, try again with the --detach option.\n") \
                if False else None
            raise Fatal("a branch is expected, got %s '%s'\nhint: If you want to detach HEAD at the commit, "
                        "try again with the --detach option." % (typ, name))
    except (BadRevision, ObjectNotFound):
        pass
    raise Fatal("invalid reference: %s" % name)
