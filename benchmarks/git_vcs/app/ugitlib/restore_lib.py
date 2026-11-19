"""Path-restoring logic shared by ``git restore`` and ``git checkout -- <paths>``."""
import os

from . import checkout as C
from .index import Index, flatten_tree
from .objects import ObjectNotFound
from .pathspec import Pathspec
from .repo import BadRevision
from .util import Fatal, err, fsencode
from .worktree import entry_state


def restore_paths(ctx, repo, paths, source=None, staged=False, worktree=True, ours=False, theirs=False,
                  checkout_style=False, report=False):
    if not paths:
        raise Fatal("you must specify path(s) to restore")
    index = Index.load(repo)
    spec = Pathspec(repo, paths)
    src_map = None
    label = "the index"
    count = 0
    if source is not None:
        try:
            sha = repo.resolve(source)
            tree = repo.peel(sha, "tree")
            label = repo.odb.shorten(tree)
        except (BadRevision, ObjectNotFound):
            raise Fatal(("invalid reference: %s" if checkout_style else "could not resolve %s") % source)
        src_map = flatten_tree(repo, tree)
    elif staged:
        h = repo.head_sha()
        if h is None:
            raise Fatal("could not resolve HEAD")
        src_map = C.commit_map(repo, h)
    stage_no = 2 if ours else 3 if theirs else None

    # candidate paths: from the source (or index) and the index
    index_paths = {e.path for e in index.sorted_entries()}
    universe = set(index_paths)
    if src_map is not None:
        universe = set(src_map) if checkout_style else universe | set(src_map)
    selected = sorted((p for p in universe if spec.match(p)), key=fsencode)
    for item in spec.includes:
        if not any(item.match(p) for p in selected):
            err("error: pathspec '%s' did not match any file(s) known to git\n" % item.orig)
            return 1
    rc = 0
    changed_index = False
    unmerged_err = []
    for p in selected:
        if stage_no is not None:
            e = index.get(p, stage_no)
            if e is None:
                if index.has_path(p) and index.get(p, 0) is None:
                    err("error: path '%s' does not have %s version\n" % (p, "our" if ours else "their"))
                    rc = 1
                continue
            if worktree:
                st = C.write_file(repo, p, e.mode, e.sha)
            continue
        if src_map is None:
            # restore worktree from the index
            if index.get(p, 0) is None and index.has_path(p):
                err("error: path '%s' is unmerged\n" % p)
                rc = 1
                continue
            e = index.get(p, 0)
            if e is None:
                continue
            if worktree and entry_state(repo, index, e) != "clean":
                st = C.write_file(repo, p, e.mode, e.sha)
                count += 1
                if not _same(e, st):
                    ne = e.copy()
                    ne.set_stat(st)
                    index.add(ne)
                    changed_index = True
            continue
        t = src_map.get(p)
        if t is None and checkout_style:
            continue  # `git checkout <tree> -- <paths>` overlays; it never deletes
        if staged:
            if t is None:
                if index.has_path(p):
                    index.remove(p)
                    changed_index = True
            else:
                from .index import IndexEntry
                cur = index.get(p, 0)
                if cur is None or (cur.mode, cur.sha) != t:
                    index.add(IndexEntry(p, t[1], t[0], 0))
                    changed_index = True
        if worktree:
            if t is None:
                if p in index_paths or not staged:
                    C.remove_file(repo, p)
            else:
                st = C.write_file(repo, p, t[0], t[1])
                count += 1
                if staged:
                    cur = index.get(p, 0)
                    if cur is not None:
                        cur.set_stat(st)
                        changed_index = True
    if changed_index:
        C.refresh_index(repo, index)
        index.write(repo)
    if report and rc == 0:
        err("Updated %d path%s from %s\n" % (count, "" if count == 1 else "s", label))
    return rc


def _same(e, st):
    from .worktree import stat_matches
    return stat_matches(e, st)
