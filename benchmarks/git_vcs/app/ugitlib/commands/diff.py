"""git diff"""
import os

from .. import diff as D
from ..diffout import DiffOpts, emit, parse_option
from ..index import Index, flatten_tree, head_tree_map
from ..objects import EMPTY_TREE, ObjectNotFound
from ..pathspec import Pathspec
from ..repo import BadRevision
from ..revwalk import merge_bases
from ..util import Fatal, out
from ..worktree import entry_state, lstat, mode_from_stat, trust_filemode, read_worktree_file
from .. import worktree
import stat as statmod


def bad_arg(arg):
    return Fatal("ambiguous argument '%s': unknown revision or path not in the working tree.\n"
                 "Use '--' to separate paths from revisions, like this:\n"
                 "'git <command> [<revision>...] -- [<file>...]'" % arg)


def tree_of(repo, spec):
    sha = repo.resolve(spec)
    return repo.peel(sha, "tree")


def worktree_side(repo, path, st, old_mode=None):
    mode = mode_from_stat(st, trust_filemode(repo), old_mode)
    return D.Side(mode, None, loader=lambda: read_worktree_file(repo, path))


def build_pairs(repo, o, mode, revs, spec):
    """mode: 'worktree' | 'cached'; revs: resolved commit/tree specs."""
    index = Index.load(repo)
    ok = (lambda p: True) if spec is None else spec.match
    unmerged = sorted({e.path for e in index.sorted_entries() if e.stage and ok(e.path)})

    def flat(spec_):
        return {p: v for p, v in flatten_tree(repo, tree_of(repo, spec_)).items() if ok(p)}

    if len(revs) == 2:
        left = D.tree_sides(repo, flat(revs[0]))
        right = D.tree_sides(repo, flat(revs[1]))
    elif mode == "cached":
        if revs:
            left = D.tree_sides(repo, flat(revs[0]))
        else:
            left = D.tree_sides(repo, {p: v for p, v in head_tree_map(repo).items() if ok(p)})
        right = {e.path: D.blob_side(repo, e.mode, e.sha) for e in index.stage0() if ok(e.path)}
        for p in unmerged:
            left.pop(p, None)
            right.pop(p, None)
    else:
        if revs:
            left = D.tree_sides(repo, flat(revs[0]))
            right = {}
            for e in index.stage0():
                if not ok(e.path):
                    continue
                state = entry_state(repo, index, e)
                if state == "clean":
                    right[e.path] = D.blob_side(repo, e.mode, e.sha)
                elif state == "modified":
                    right[e.path] = worktree_side(repo, e.path, lstat(repo, e.path), e.mode)
        else:
            left, right = {}, {}
            for e in index.stage0():
                if not ok(e.path):
                    continue
                state = entry_state(repo, index, e)
                if state == "clean":
                    continue
                left[e.path] = D.blob_side(repo, e.mode, e.sha)
                if state == "modified":
                    right[e.path] = worktree_side(repo, e.path, lstat(repo, e.path), e.mode)
        for p in unmerged:
            left.pop(p, None)
            right.pop(p, None)
    pairs = D.maps_to_pairs(repo, left, right)
    if o.renames:
        pairs = D.detect_renames(pairs)
    return pairs, unmerged


def run(ctx, args):
    o = DiffOpts()
    cached = False
    words = []
    paths = []
    i = 0
    dashdash = False
    while i < len(args):
        a = args[i]
        if a == "--":
            dashdash = True
            paths = args[i + 1:]
            break
        if a in ("--cached", "--staged"):
            cached = True
        elif parse_option(o, a):
            pass
        elif a.startswith("-") and len(a) > 1:
            raise Fatal("unrecognized argument: %s" % a, 129)
        else:
            words.append(a)
        i += 1
    repo = ctx.repo()
    revs = []
    if not dashdash:
        for k, w in enumerate(words):
            if len(revs) < 2 and ".." in w and not os.path.exists(w):
                a_, sep, b_ = w.partition("...") if "..." in w else w.partition("..")
                sep = "..." if "..." in w else ".."
                try:
                    ra = repo.resolve_commit(a_ or "HEAD")
                    rb = repo.resolve_commit(b_ or "HEAD")
                except (BadRevision, ObjectNotFound):
                    raise bad_arg(w)
                if sep == "...":
                    mb = merge_bases(repo, ra, rb)
                    if not mb:
                        raise Fatal("%s...%s: no merge base" % (a_, b_))
                    ra = mb[0]
                revs += [ra, rb]
                continue
            try:
                sha = repo.resolve(w)
                if repo.odb.exists(sha):
                    revs.append(w)
                    continue
            except (BadRevision, ObjectNotFound):
                pass
            if os.path.lexists(os.path.join(ctx.cwd, w)):
                paths = words[k:]
                break
            raise bad_arg(w)
    else:
        for w in words:
            try:
                sha = repo.resolve(w)
                if not repo.odb.exists(sha):
                    raise BadRevision(w)
                revs.append(w)
            except (BadRevision, ObjectNotFound):
                raise bad_arg(w)
    if len(revs) > 2:
        raise Fatal("too many revisions")
    if repo.worktree is None and not cached and len(revs) < 2:
        cached = True
    spec = Pathspec(repo, paths) if paths else None
    pairs, unmerged = build_pairs(repo, o, "cached" if cached else "worktree", revs, spec)
    for p in unmerged:
        if o.wants_patch(True) or o.any_format():
            out("* Unmerged path %s\n" % p)
    emit(repo, pairs, o)
    if o.exit_code and (pairs or unmerged):
        return 1
    return 0
