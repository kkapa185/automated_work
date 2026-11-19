"""git mv"""
import os

from ..index import Index
from ..pathspec import normalize_path
from ..util import Fatal, out, usage_error, unknown_opt_msg
from ..worktree import lstat, stat_matches

USAGE = "git mv [<options>] <source>... <destination>"


def run(ctx, args):
    force = dry = verbose = skip = False
    pos = []
    for a in args:
        if a in ("-f", "--force"):
            force = True
        elif a in ("-n", "--dry-run"):
            dry = True
        elif a in ("-v", "--verbose"):
            verbose = True
        elif a == "-k":
            skip = True
        elif a.startswith("-") and a != "-" and len(a) > 1:
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
    if len(pos) < 2:
        raise Fatal(USAGE, 129, prefix="usage: ")
    repo = ctx.worktree_repo()
    index = Index.load(repo)
    wt = repo.worktree
    srcs = [normalize_path(repo, s) for s in pos[:-1]]
    dst = normalize_path(repo, pos[-1])
    dst_is_dir = os.path.isdir(os.path.join(wt, dst)) and not os.path.islink(os.path.join(wt, dst))
    if len(srcs) > 1 and not dst_is_dir:
        raise Fatal("destination '%s' is not a directory" % pos[-1])
    plan = []  # (src, dst)
    for s in srcs:
        d = dst + "/" + os.path.basename(s) if dst_is_dir else dst
        d = d.lstrip("/")
        err_msg = None
        st = lstat(repo, s)
        if st is None:
            err_msg = "bad source"
        elif index.is_dir(s) and not index.has_path(s):
            pass
        elif not index.has_path(s):
            err_msg = "not under version control" if not os.path.isdir(os.path.join(wt, s)) \
                else "source directory is empty"
        elif index.get(s, 0) is None:
            err_msg = "conflicted"
        if err_msg is None and (d == s or d.startswith(s + "/")):
            err_msg = "can not move directory into itself"
        if err_msg is None and os.path.lexists(os.path.join(wt, d)) and not force:
            err_msg = "destination exists"
        if err_msg is None and os.path.lexists(os.path.join(wt, d)) and force:
            if os.path.isdir(os.path.join(wt, d)):
                err_msg = "destination exists"
        if err_msg:
            if skip:
                continue
            raise Fatal("%s, source=%s, destination=%s" % (err_msg, s, d))
        plan.append((s, d))
    for s, d in plan:
        if verbose or dry:
            out("Renaming %s to %s\n" % (s, d))
        if dry:
            continue
        sfull, dfull = os.path.join(wt, s), os.path.join(wt, d)
        old_clean = {}
        moved = index.under(s) if index.is_dir(s) and not index.has_path(s) else index.stages(s)
        for e in moved:
            st0 = lstat(repo, e.path)
            old_clean[e.path] = st0 is not None and stat_matches(e, st0)
        try:
            if os.path.lexists(dfull) and not os.path.isdir(dfull):
                os.unlink(dfull)
            os.rename(sfull, dfull)
        except OSError as e:
            raise Fatal("renaming '%s' failed: %s" % (s, e.strerror))
        for e in moved:
            index.remove(e.path)
            ne = e.copy()
            ne.path = d + e.path[len(s):]
            if old_clean.get(e.path):
                st = lstat(repo, ne.path)
                if st is not None:
                    ne.set_stat(st)
            index.add(ne)
    if plan and not dry:
        index.write(repo)
    return 0
