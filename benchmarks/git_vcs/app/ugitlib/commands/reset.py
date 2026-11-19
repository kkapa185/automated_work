"""git reset"""
import os

from .. import checkout as C
from .. import statuslib
from ..index import Index, IndexEntry, flatten_tree
from ..objects import ObjectNotFound
from ..pathspec import Pathspec
from ..repo import BadRevision
from ..util import Fatal, err, fsencode, out, usage_error, unknown_opt_msg
from .checkout import subject_of

USAGE = "git reset [--mixed | --soft | --hard | --merge | --keep] [-q] [<commit>]"
STATE_FILES = ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "SQUASH_MSG", "AUTO_MERGE")


def bad_arg(arg):
    return Fatal("ambiguous argument '%s': unknown revision or path not in the working tree.\n"
                 "Use '--' to separate paths from revisions, like this:\n"
                 "'git <command> [<revision>...] -- [<file>...]'" % arg)


def report_unstaged(repo, index_unused=None):
    st = statuslib.compute(repo, "no")
    lines = []
    for code, path in st.unstaged:
        lines.append("%s\t%s\n" % ("M" if code in ("M", "T") else code, path))
    for path in sorted(st.unmerged, key=fsencode):
        lines.append("U\t%s\n" % path)
    if lines:
        out("Unstaged changes after reset:\n" + "".join(lines))


def run(ctx, args):
    mode = None
    quiet = False
    pos = []
    dashdash = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            dashdash = args[i + 1:]
            break
        if a in ("--soft", "--mixed", "--hard"):
            mode = a[2:]
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
        i += 1
    repo = ctx.worktree_repo()
    rev = None
    paths = []
    if dashdash is not None:
        if len(pos) > 1:
            raise Fatal(USAGE, 129, prefix="usage: ")
        rev = pos[0] if pos else None
        paths = dashdash
    else:
        if pos:
            first = pos[0]
            try:
                sha = repo.resolve(first)
                if not repo.odb.exists(sha):
                    raise BadRevision(first)
                rev = first
                paths = pos[1:]
            except (BadRevision, ObjectNotFound):
                if all(os.path.lexists(os.path.join(ctx.cwd, p)) or True for p in pos) and \
                        any(os.path.lexists(os.path.join(ctx.cwd, p)) for p in pos):
                    paths = pos
                else:
                    raise bad_arg(first)
    head = repo.head_sha()
    if rev is not None:
        try:
            target = repo.resolve_commit(rev) if not paths else repo.peel(repo.resolve(rev), "tree")
        except (BadRevision, ObjectNotFound):
            raise bad_arg(rev)
    else:
        target = head
    if paths or dashdash is not None and paths:
        if mode in ("soft", "hard"):
            raise Fatal("Cannot do %s reset with paths." % mode)
        return reset_paths(repo, paths, rev, target, head, quiet)
    if mode is None:
        mode = "mixed"
    index = Index.load(repo)
    merge_state = os.path.exists(os.path.join(repo.gitdir, "MERGE_HEAD"))
    if mode == "soft" and (merge_state or index.has_conflicts()):
        raise Fatal("Cannot do a soft reset in the middle of a merge.")
    new_map = C.commit_map(repo, target)
    if mode == "hard":
        hard_reset(repo, index, new_map)
    elif mode == "mixed":
        mixed_reset(repo, index, new_map)
    # move the branch
    if head is not None:
        with open(os.path.join(repo.gitdir, "ORIG_HEAD"), "w") as f:
            f.write(head + "\n")
    if target is not None:
        branch = repo.refs.head_branch()
        msg = "reset: moving to %s" % (rev if rev is not None else "HEAD")
        if branch is not None:
            repo.update_ref("refs/heads/" + branch, target, msg)
        else:
            repo.update_ref("HEAD", target, msg)
    if mode != "soft":
        for f in STATE_FILES:
            try:
                os.unlink(os.path.join(repo.gitdir, f))
            except OSError:
                pass
    if mode == "hard":
        if not quiet and target is not None:
            out("HEAD is now at %s %s\n" % (repo.odb.shorten(target), subject_of(repo, target)))
    elif mode == "mixed" and not quiet:
        report_unstaged(repo)
    return 0


def mixed_reset(repo, index, new_map):
    new = Index(index.path)
    for p, (m, s) in new_map.items():
        old = index.get(p, 0)
        if old is not None and (old.mode, old.sha) == (m, s):
            new._put(old)
        else:
            new._put(IndexEntry(p, s, m, 0))
    new.mtime_ns = index.mtime_ns
    C.refresh_index(repo, new)
    new.write(repo)


def hard_reset(repo, index, new_map):
    from ..worktree import entry_state
    plan = []
    cur = {e.path: e for e in index.sorted_entries() if e.stage == 0}
    unmerged = {e.path for e in index.sorted_entries() if e.stage}
    for p in set(cur) | unmerged:
        if p not in new_map:
            plan.append((p, None))
    for p, t in new_map.items():
        e = cur.get(p)
        if p in unmerged or e is None or (e.mode, e.sha) != t or entry_state(repo, index, e) != "clean":
            plan.append((p, t))
    for p in unmerged:
        index.remove(p)
    # a tracked path replaced by a directory must be cleared first
    plan.sort(key=lambda x: (x[1] is not None, fsencode(x[0])))
    C.apply_plan(repo, index, plan)
    index.write(repo)


def reset_paths(repo, paths, rev, target, head, quiet):
    spec = Pathspec(repo, paths)
    index = Index.load(repo)
    if rev is not None:
        tree_map = flatten_tree(repo, target)
    else:
        tree_map = C.commit_map(repo, head)
    universe = set(tree_map) | {e.path for e in index.sorted_entries()}
    selected = [p for p in universe if spec.match(p)]
    for p in selected:
        t = tree_map.get(p)
        old = index.get(p, 0)
        if t is None:
            index.remove(p)
        elif old is None or (old.mode, old.sha) != t:
            index.add(IndexEntry(p, t[1], t[0], 0))
    C.refresh_index(repo, index)
    index.write(repo)
    if not quiet:
        report_unstaged(repo)
    return 0
