"""git restore"""
from ..restore_lib import restore_paths
from ..util import Fatal, expand_short, usage_error, unknown_opt_msg

USAGE = "git restore [<options>] [--source=<branch>] <file>..."


def run(ctx, args):
    args = expand_short(args, "SWq", "s")
    staged = worktree = False
    source = None
    ours = theirs = False
    paths = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-S", "--staged"):
            staged = True
        elif a in ("-W", "--worktree"):
            worktree = True
        elif a in ("-s", "--source"):
            i += 1
            if i >= len(args):
                usage_error("switch `s' requires a value", USAGE)
            source = args[i]
        elif a.startswith("--source="):
            source = a.split("=", 1)[1]
        elif a == "--ours":
            ours = True
        elif a == "--theirs":
            theirs = True
        elif a in ("-q", "--quiet", "--no-progress", "--progress", "--ignore-unmerged", "-p", "--patch"):
            pass
        elif a == "--":
            paths += args[i + 1:]
            break
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            paths.append(a)
        i += 1
    repo = ctx.worktree_repo()
    if not paths:
        raise Fatal("you must specify path(s) to restore")
    if not staged and not worktree:
        worktree = True
    return restore_paths(ctx, repo, paths, source=source, staged=staged, worktree=worktree,
                         ours=ours, theirs=theirs)
