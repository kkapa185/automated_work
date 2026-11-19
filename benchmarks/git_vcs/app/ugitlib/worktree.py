"""Worktree helpers: stat comparison, hashing, directory walking."""
import os
import stat

from .index import IndexEntry
from .objects import hash_object
from .util import fsencode


def mode_from_stat(st, trust_exec=True, old_mode=None):
    if stat.S_ISLNK(st.st_mode):
        return 0o120000
    if stat.S_ISDIR(st.st_mode):
        return 0o160000
    if trust_exec:
        return 0o100755 if st.st_mode & 0o100 else 0o100644
    if old_mode in (0o100644, 0o100755):
        return old_mode
    return 0o100644


def trust_filemode(repo):
    return repo.config.get_bool("core.filemode", True)


def read_worktree_file(repo, path):
    """Content as it would be stored in a blob (symlinks: link target)."""
    full = os.path.join(repo.worktree, path)
    if os.path.islink(full):
        return fsencode(os.readlink(full))
    with open(full, "rb") as f:
        return f.read()


def lstat(repo, path):
    try:
        return os.lstat(os.path.join(repo.worktree, path))
    except (FileNotFoundError, NotADirectoryError):
        return None


def stat_matches(e, st):
    """Cheap stat-based "unchanged" test (size, mtime, ctime, ino, dev, uid, gid)."""
    m = 10 ** 9
    mt, mtn = divmod(st.st_mtime_ns, m)
    ct, ctn = divmod(st.st_ctime_ns, m)
    return (e.size == (st.st_size & 0xFFFFFFFF) and e.mtime == (mt & 0xFFFFFFFF) and e.mtime_ns == mtn
            and e.ctime == (ct & 0xFFFFFFFF) and e.ctime_ns == ctn
            and e.ino == (st.st_ino & 0xFFFFFFFF) and e.dev == (st.st_dev & 0xFFFFFFFF)
            and e.uid == (st.st_uid & 0xFFFFFFFF) and e.gid == (st.st_gid & 0xFFFFFFFF))


def is_racy(index, e):
    """An entry whose mtime is not older than the index file may be stale despite equal stat data."""
    return (e.mtime * 10 ** 9 + e.mtime_ns) >= index.mtime_ns


def entry_state(repo, index, e, trust_exec=None):
    """Compare a stage-0 entry with the worktree: 'missing', 'modified' or 'clean'."""
    if trust_exec is None:
        trust_exec = trust_filemode(repo)
    st = lstat(repo, e.path)
    if st is None or (stat.S_ISDIR(st.st_mode) and e.mode != 0o160000):
        return "missing"
    if e.mode == 0o160000:
        return "clean"
    if e.assume_valid:
        return "clean"
    mode = mode_from_stat(st, trust_exec, e.mode)
    if mode != e.mode and (trust_exec or (mode >> 12) != (e.mode >> 12)):
        return "modified"
    if stat_matches(e, st) and not is_racy(index, e):
        return "clean"
    if e.size != (st.st_size & 0xFFFFFFFF) and not stat.S_ISLNK(st.st_mode):
        return "modified"
    try:
        data = read_worktree_file(repo, e.path)
    except OSError:
        return "missing"
    return "clean" if hash_object("blob", data) == e.sha else "modified"


def make_entry(repo, path, st, old=None, write=True):
    """Build (and store the blob for) an index entry for worktree file ``path``."""
    data = read_worktree_file(repo, path)
    sha = repo.odb.write("blob", data) if write else hash_object("blob", data)
    mode = mode_from_stat(st, trust_filemode(repo), old.mode if old else None)
    return IndexEntry(path, sha, mode, 0, st)


def walk_untracked(repo, index, ignore, pathspec=None, mode="untracked", collapse=False):
    """List worktree paths not in the index.

    mode: 'untracked' (not ignored), 'ignored' (only ignored), 'all' (both).
    With ``collapse`` fully untracked directories are reported once as ``dir/``.
    Returns a bytewise-sorted list of paths."""
    wt = repo.worktree
    result = []

    def want(ign):
        return mode == "all" or (mode == "ignored") == ign

    def walk(d, parent_ign):
        """Returns True if anything was reported under d."""
        reported = False
        try:
            with os.scandir(os.path.join(wt, d) if d else wt) as it:
                entries = sorted(it, key=lambda e: fsencode(e.name))
        except OSError:
            return False
        for ent in entries:
            name = ent.name
            if name == ".git":
                continue
            path = d + "/" + name if d else name
            try:
                is_dir = ent.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if os.path.exists(os.path.join(wt, path, ".git")):
                    continue  # nested repository
                if pathspec and not pathspec.may_contain(path):
                    continue
                ign = parent_ign or ignore.is_ignored(path, True)
                if ign and mode == "untracked":
                    continue
                tracked_below = index.is_dir(path)
                if collapse and ign and mode == "ignored" and not tracked_below and not parent_ign:
                    sub_start = len(result)
                    if walk(path, ign):
                        del result[sub_start:]
                        result.append(path + "/")
                        reported = True
                    continue
                if collapse and not tracked_below and not ign and mode == "untracked":
                    sub_start = len(result)
                    found = walk(path, ign)
                    if found:
                        del result[sub_start:]
                        result.append(path + "/")
                        reported = True
                    continue
                if walk(path, ign):
                    reported = True
            else:
                if pathspec and not pathspec.match(path):
                    continue
                if index.has_path(path):
                    continue
                ign = parent_ign or ignore.is_ignored(path, False)
                if want(ign):
                    result.append(path)
                    reported = True
        return reported

    walk("", False)
    result.sort(key=fsencode)
    return result
