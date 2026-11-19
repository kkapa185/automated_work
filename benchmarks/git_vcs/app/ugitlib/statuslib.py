"""Compute repository status: staged (HEAD vs index), unstaged (index vs worktree), untracked."""
import os
import stat

from . import diff as D
from .ignore import IgnoreMatcher
from .index import Index, flatten_tree, head_tree_map
from .util import fsencode
from .worktree import entry_state, lstat, walk_untracked


class Status:
    pass


def staged_pairs(repo, index, detect_renames=True, head=None):
    if head is None:
        head = head_tree_map(repo)
    left = D.tree_sides(repo, head)
    right = {e.path: D.blob_side(repo, e.mode, e.sha) for e in index.stage0()}
    # unmerged paths are reported separately
    unmerged = {e.path for e in index.sorted_entries() if e.stage}
    for p in unmerged:
        left.pop(p, None)
        right.pop(p, None)
    pairs = D.maps_to_pairs(repo, left, right)
    if detect_renames:
        pairs = D.detect_renames(pairs)
    return pairs


def compute(repo, untracked_mode="normal", ignored=False, pathspec=None, amend=False):
    st = Status()
    index = Index.load(repo)
    st.index = index
    st.head = repo.head_sha()
    st.branch = repo.refs.head_branch()
    if amend and st.head:
        # `commit --amend` reports against the parent of HEAD (the state after amending)
        parents = repo.read_commit(st.head).parents
        st.head = parents[0] if parents else None
        base = flatten_tree(repo, repo.read_commit(st.head).tree) if st.head else {}
        st.staged = staged_pairs(repo, index, head=base)
    else:
        st.staged = staged_pairs(repo, index)
    unmerged = {}
    for e in index.sorted_entries():
        if e.stage:
            unmerged.setdefault(e.path, set()).add(e.stage)
    st.unmerged = unmerged
    # unstaged: index vs worktree
    st.unstaged = []  # (code, path)
    for e in index.stage0():
        if e.path in unmerged:
            continue
        state = entry_state(repo, index, e)
        if state == "clean":
            continue
        if state == "missing":
            st.unstaged.append(("D", e.path))
        else:
            s = lstat(repo, e.path)
            code = "M"
            if s is not None:
                new_type = 0o120000 if stat.S_ISLNK(s.st_mode) else 0o100000
                if (e.mode & 0o170000) != new_type:
                    code = "T"
            st.unstaged.append((code, e.path))
    st.untracked = []
    st.ignored = []
    ignore = IgnoreMatcher(repo)
    if untracked_mode != "no":
        st.untracked = walk_untracked(repo, index, ignore, pathspec, "untracked",
                                      collapse=(untracked_mode == "normal"))
    if ignored:
        st.ignored = walk_untracked(repo, index, ignore, pathspec, "ignored",
                                    collapse=(untracked_mode == "normal"))
    return st
