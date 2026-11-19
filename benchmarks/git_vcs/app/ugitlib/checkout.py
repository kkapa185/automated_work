"""Moving between trees: switching branches, resets and path restores.

``plan_switch`` implements the two-way merge rules (HEAD tree -> target tree) that decide which
paths may be updated without losing local work; ``apply_plan`` performs the file operations."""
import os
import shutil
import stat

from . import diff as D
from .index import Index, IndexEntry, flatten_tree
from .util import Fatal, err, fsdecode, fsencode
from .worktree import entry_state, lstat, trust_filemode


class Abort(Exception):
    """A refused operation; ``text`` is the full stderr output (without trailing newline)."""

    def __init__(self, text):
        super().__init__(text)
        self.text = text


def commit_map(repo, sha):
    if sha is None:
        return {}
    return flatten_tree(repo, repo.read_commit(sha).tree)


def _tuple(e):
    return (e.mode, e.sha) if e is not None else None


def write_file(repo, path, mode, sha):
    """Materialise blob ``sha`` at worktree ``path``; returns the resulting lstat."""
    wt = repo.worktree
    full = os.path.join(wt, path)
    parts = path.split("/")
    cur = wt
    for part in parts[:-1]:
        cur = os.path.join(cur, part)
        if os.path.lexists(cur) and (os.path.islink(cur) or not os.path.isdir(cur)):
            os.unlink(cur)
        if not os.path.isdir(cur):
            os.mkdir(cur)
    if os.path.lexists(full):
        if os.path.isdir(full) and not os.path.islink(full):
            if mode == 0o160000:
                return os.lstat(full)
            try:
                os.rmdir(full)
            except OSError:
                raise Abort("error: cannot replace directory '%s': it contains untracked files" % path)
        else:
            os.unlink(full)
    if mode == 0o160000:
        os.mkdir(full)
        return os.lstat(full)
    data = repo.odb.read(sha)[1]
    if mode == 0o120000:
        os.symlink(fsdecode(data), full)
    else:
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o777 if mode == 0o100755 else 0o666)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    return os.lstat(full)


def remove_file(repo, path):
    wt = repo.worktree
    full = os.path.join(wt, path)
    try:
        if os.path.isdir(full) and not os.path.islink(full):
            os.rmdir(full)
        else:
            os.unlink(full)
    except OSError:
        pass
    d = os.path.dirname(full)
    while d != wt and d.startswith(wt):
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)


def _untracked_in_way(repo, index, path):
    wt = repo.worktree
    full = os.path.join(wt, path)
    if os.path.lexists(full):
        if os.path.isdir(full) and not os.path.islink(full):
            for root, dirs, files in os.walk(full):
                for fn in files:
                    rel = os.path.relpath(os.path.join(root, fn), wt)
                    if not index.has_path(rel):
                        return True
            return False
        return True
    parts = path.split("/")
    cur = wt
    for part in parts[:-1]:
        cur = os.path.join(cur, part)
        if os.path.lexists(cur) and (os.path.islink(cur) or not os.path.isdir(cur)):
            rel = os.path.relpath(cur, wt)
            if not index.has_path(rel):
                return True
    return False


def refusal(op, overwritten, untracked, dirty=(), removed=()):
    """Build git's multi-part refusal message (one block per kind of problem)."""
    verb = "switch branches" if op == "checkout" else op
    blocks = []
    for group in (overwritten, dirty):
        if group:
            blocks.append("error: Your local changes to the following files would be overwritten by %s:\n%s\n"
                          "Please commit your changes or stash them before you %s." % (
                              op, "\n".join("\t" + p for p in sorted(group, key=fsencode)), verb))
    if untracked:
        blocks.append("error: The following untracked working tree files would be overwritten by %s:\n%s\n"
                      "Please move or remove them before you %s." % (
                          op, "\n".join("\t" + p for p in sorted(untracked, key=fsencode)), verb))
    if removed:
        blocks.append("error: The following untracked working tree files would be removed by %s:\n%s\n"
                      "Please move or remove them before you %s." % (
                          op, "\n".join("\t" + p for p in sorted(removed, key=fsencode)), verb))
    return "\n".join(blocks) + "\nAborting"


def plan_switch(repo, index, old, new, force=False, op="checkout"):
    """Decide per-path actions to go from tree ``old`` to ``new`` keeping local changes.

    Returns list of (path, new_tuple_or_None). Raises Abort when local work would be lost."""
    unmerged = {e.path for e in index.sorted_entries() if e.stage}
    if unmerged and not force:
        raise Abort("error: you need to resolve your current index first")
    plan = []
    overwritten, untracked, dirty, removed = [], [], [], []
    paths = set(old) | set(new) | {e.path for e in index.sorted_entries()}
    for p in sorted(paths, key=fsencode):
        h, t = old.get(p), new.get(p)
        e = index.get(p, 0)
        ie = _tuple(e)
        if p in unmerged:
            plan.append((p, t))
            continue
        if h == t:
            if force and e is not None and t is not None and (ie != t or entry_state(repo, index, e) != "clean"):
                plan.append((p, t))
            elif force and e is not None and t is None:
                plan.append((p, None))
            elif force and e is None and t is not None:
                plan.append((p, t))
            continue
        if not force and h is not None and t is None and e is None and \
                os.path.lexists(os.path.join(repo.worktree, p)):
            removed.append(p)
            continue
        if ie == t and not force:
            continue
        if force:
            plan.append((p, t))
            continue
        if ie == h:
            if e is not None:
                if entry_state(repo, index, e) == "modified":
                    dirty.append(p)
                    continue
            elif t is not None and _untracked_in_way(repo, index, p):
                untracked.append(p)
                continue
            plan.append((p, t))
        else:
            overwritten.append(p)
    if overwritten or untracked or dirty or removed:
        raise Abort(refusal(op, overwritten, untracked, dirty, removed))
    return plan


def apply_plan(repo, index, plan):
    for p, t in plan:
        if t is None:
            remove_file(repo, p)
            index.remove(p)
    for p, t in plan:
        if t is not None:
            st = write_file(repo, p, t[0], t[1])
            index.add(IndexEntry(p, t[1], t[0], 0, st))


def refresh_index(repo, index):
    """Fill in stat data of entries that have none when the worktree file matches."""
    from .objects import hash_object
    from .worktree import read_worktree_file
    for e in index.stage0():
        if e.mtime or e.ctime or e.mode == 0o160000:
            continue
        st = lstat(repo, e.path)
        if st is None or stat.S_ISDIR(st.st_mode):
            continue
        try:
            if hash_object("blob", read_worktree_file(repo, e.path)) == e.sha:
                e.set_stat(st)
        except OSError:
            pass


def set_head_detached(repo, sha):
    repo.refs.write_raw("HEAD", sha + "\n")


def checkout_paths_from_index(repo, index, entries):
    count = 0
    for e in entries:
        st = write_file(repo, e.path, e.mode, e.sha)
        ne = e.copy()
        ne.set_stat(st)
        index.add(ne)
        count += 1
    return count
