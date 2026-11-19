"""The git index (staging area): binary format versions 2/3 (and v4 read), byte-compatible with git.

Layout::

    "DIRC" | version(4) | count(4)
    entry*   (62 bytes fixed + path, NUL padded so each entry is a multiple of 8 bytes)
    extensions*  (4-byte signature, 4-byte size, data)   -- skipped on read, not written
    SHA-1 checksum of everything before it

Entry: ctime s/ns, mtime s/ns, dev, ino, mode, uid, gid, size (10 x uint32), sha (20), flags (16 bits:
assume-valid 0x8000, extended 0x4000, stage 0x3000, name length 0x0FFF), [extended flags (16 bits) in v3],
path, NUL padding (1-8 bytes).
"""
import hashlib
import os
import struct
import time

from .objects import build_tree, parse_commit, parse_tree
from .util import Fatal, fsdecode, fsencode

SIG = b"DIRC"
FLAG_ASSUME_VALID = 0x8000
FLAG_EXTENDED = 0x4000
EXT_SKIP_WORKTREE = 0x4000
EXT_INTENT_TO_ADD = 0x2000


class IndexEntry:
    __slots__ = ("ctime", "ctime_ns", "mtime", "mtime_ns", "dev", "ino", "mode", "uid", "gid",
                 "size", "sha", "stage", "assume_valid", "ext", "path")

    def __init__(self, path, sha, mode, stage=0, st=None):
        self.path = path
        self.sha = sha
        self.mode = mode
        self.stage = stage
        self.assume_valid = False
        self.ext = 0
        self.ctime = self.ctime_ns = self.mtime = self.mtime_ns = 0
        self.dev = self.ino = self.uid = self.gid = self.size = 0
        if st is not None:
            self.set_stat(st)

    def set_stat(self, st):
        m = 10 ** 9
        self.ctime, self.ctime_ns = divmod(st.st_ctime_ns, m)
        self.mtime, self.mtime_ns = divmod(st.st_mtime_ns, m)
        self.ctime &= 0xFFFFFFFF
        self.mtime &= 0xFFFFFFFF
        self.dev = st.st_dev & 0xFFFFFFFF
        self.ino = st.st_ino & 0xFFFFFFFF
        self.uid = st.st_uid & 0xFFFFFFFF
        self.gid = st.st_gid & 0xFFFFFFFF
        self.size = st.st_size & 0xFFFFFFFF

    def copy(self):
        e = IndexEntry(self.path, self.sha, self.mode, self.stage)
        for s in self.__slots__:
            setattr(e, s, getattr(self, s))
        return e

    def pack(self):
        name = fsencode(self.path)
        flags = (self.stage << 12) | min(len(name), 0xFFF)
        if self.assume_valid:
            flags |= FLAG_ASSUME_VALID
        if self.ext:
            flags |= FLAG_EXTENDED
        head = struct.pack(">10I20sH", self.ctime, self.ctime_ns, self.mtime, self.mtime_ns,
                           self.dev, self.ino, self.mode, self.uid, self.gid, self.size,
                           bytes.fromhex(self.sha), flags)
        if self.ext:
            head += struct.pack(">H", self.ext)
        raw = head + name
        pad = 8 - (len(raw) % 8)
        return raw + b"\0" * pad


def _parent_dirs(path):
    i = path.find("/")
    while i >= 0:
        yield path[:i]
        i = path.find("/", i + 1)


class Index:
    def __init__(self, path=None):
        self.path = path
        self.entries = {}          # (path, stage) -> IndexEntry
        self.dirs = {}             # directory path -> number of entries below it
        self.version = 2
        self.mtime_ns = 0          # mtime of the index file when loaded (racy-git check)

    # ---- loading
    @classmethod
    def path_for(cls, repo):
        return repo.env.get("GIT_INDEX_FILE") or os.path.join(repo.gitdir, "index")

    @classmethod
    def load(cls, repo):
        idx = cls(cls.path_for(repo))
        try:
            with open(idx.path, "rb") as f:
                data = f.read()
            idx.mtime_ns = os.stat(idx.path).st_mtime_ns
        except FileNotFoundError:
            return idx
        idx._parse(data)
        return idx

    def _parse(self, data):
        if len(data) < 32 or data[:4] != SIG:
            raise Fatal("index file corrupt")
        if hashlib.sha1(data[:-20]).digest() != data[-20:]:
            raise Fatal("index file corrupt: bad checksum")
        version, count = struct.unpack(">II", data[4:12])
        if version not in (2, 3, 4):
            raise Fatal("index file has unsupported version %d" % version)
        self.version = version
        pos = 12
        prev = b""
        for _ in range(count):
            (ct, ctn, mt, mtn, dev, ino, mode, uid, gid, size, sha, flags) = struct.unpack(
                ">10I20sH", data[pos:pos + 62])
            start = pos
            pos += 62
            ext = 0
            if flags & FLAG_EXTENDED:
                ext = struct.unpack(">H", data[pos:pos + 2])[0]
                pos += 2
            if version == 4:
                # prefix-compressed path: varint = bytes to strip from previous path
                c = data[pos]
                pos += 1
                strip = c & 0x7F
                while c & 0x80:
                    c = data[pos]
                    pos += 1
                    strip = ((strip + 1) << 7) | (c & 0x7F)
                end = data.index(b"\0", pos)
                name = prev[:len(prev) - strip] + data[pos:end]
                pos = end + 1
                prev = name
            else:
                n = flags & 0xFFF
                if n < 0xFFF:
                    name = data[pos:pos + n]
                    pos += n
                else:
                    end = data.index(b"\0", pos)
                    name = data[pos:end]
                    pos = end
                pos = start + ((pos - start + 8) & ~7)
            e = IndexEntry(fsdecode(name), sha.hex(), mode, (flags >> 12) & 3)
            e.ctime, e.ctime_ns, e.mtime, e.mtime_ns = ct, ctn, mt, mtn
            e.dev, e.ino, e.uid, e.gid, e.size = dev, ino, uid, gid, size
            e.assume_valid = bool(flags & FLAG_ASSUME_VALID)
            e.ext = ext
            self._put(e)
        # extensions are optional for correctness; the cache-tree etc. are rebuilt by git on demand.
        end = len(data) - 20
        while pos + 8 <= end:
            sig = data[pos:pos + 4]
            size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
            if sig[0:1].islower() and sig not in (b"link", b"sdir"):
                pass
            elif sig[0:1].islower():
                raise Fatal("index uses unsupported extension %s" % sig.decode("latin1"))
            pos += 8 + size

    # ---- bookkeeping
    def _put(self, e):
        key = (e.path, e.stage)
        if key not in self.entries:
            for d in _parent_dirs(e.path):
                self.dirs[d] = self.dirs.get(d, 0) + 1
        self.entries[key] = e

    def _drop(self, key):
        e = self.entries.pop(key, None)
        if e is not None:
            for d in _parent_dirs(e.path):
                n = self.dirs.get(d, 0) - 1
                if n <= 0:
                    self.dirs.pop(d, None)
                else:
                    self.dirs[d] = n
        return e

    # ---- queries
    def get(self, path, stage=0):
        return self.entries.get((path, stage))

    def has_path(self, path):
        return any((path, s) in self.entries for s in range(4))

    def stages(self, path):
        return [self.entries[(path, s)] for s in range(4) if (path, s) in self.entries]

    def is_dir(self, path):
        return path in self.dirs

    def sorted_entries(self):
        return [self.entries[k] for k in sorted(self.entries, key=lambda k: (fsencode(k[0]), k[1]))]

    def stage0(self):
        return [e for e in self.sorted_entries() if e.stage == 0]

    def paths(self):
        """Sorted unique paths (any stage)."""
        seen = []
        last = None
        for e in self.sorted_entries():
            if e.path != last:
                seen.append(e.path)
                last = e.path
        return seen

    def has_conflicts(self):
        return any(k[1] != 0 for k in self.entries)

    def under(self, dirpath):
        """Entries whose path is below ``dirpath`` (a directory, no trailing slash)."""
        pre = dirpath + "/" if dirpath else ""
        return [e for e in self.sorted_entries() if e.path.startswith(pre)]

    # ---- modification
    def add(self, entry, replace=True):
        """Add/replace an entry; clears other stages of the path (for stage 0) and resolves
        directory/file conflicts like git does."""
        if replace:
            if entry.stage == 0:
                for s in (1, 2, 3):
                    self._drop((entry.path, s))
            else:
                self._drop((entry.path, 0))
            for d in _parent_dirs(entry.path):
                if self.has_path(d):
                    self.remove(d)
            if entry.path in self.dirs:
                for e in self.under(entry.path):
                    self._drop((e.path, e.stage))
        self._put(entry)

    def remove(self, path):
        removed = False
        for s in range(4):
            if self._drop((path, s)) is not None:
                removed = True
        return removed

    def remove_under(self, dirpath):
        for e in self.under(dirpath):
            self._drop((e.path, e.stage))

    def clear(self):
        self.entries.clear()
        self.dirs.clear()

    # ---- writing
    def serialize(self, version=None):
        ents = self.sorted_entries()
        if version is None:
            version = 3 if any(e.ext for e in ents) else 2
        body = [SIG, struct.pack(">II", version, len(ents))]
        for e in ents:
            body.append(e.pack())
        data = b"".join(body)
        return data + hashlib.sha1(data).digest()

    def write(self, repo=None):
        path = self.path
        lock = path + ".lock"
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            raise Fatal("Unable to create '%s': File exists.\n\nAnother git process seems to be running in "
                        "this repository, e.g.\nan editor opened by 'git commit'. Please make sure all "
                        "processes\nare terminated then try again. If it still fails, a git process\n"
                        "may have crashed in this repository earlier:\nremove the file manually to "
                        "continue." % lock)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(self.serialize())
            os.replace(lock, path)
        except BaseException:
            try:
                os.unlink(lock)
            except OSError:
                pass
            raise
        try:
            self.mtime_ns = os.stat(path).st_mtime_ns
        except OSError:
            self.mtime_ns = time.time_ns()


# ---------------------------------------------------------------- tree <-> index helpers

def flatten_tree(repo, tree_sha, prefix=""):
    """Recursively list a tree as {path: (mode, sha)} for non-tree entries."""
    result = {}
    stack = [(tree_sha, prefix)]
    while stack:
        sha, pre = stack.pop()
        for mode, name, esha in repo.read_tree(sha):
            p = pre + name
            if mode == 0o40000:
                stack.append((esha, p + "/"))
            else:
                result[p] = (mode, esha)
    return result


def head_tree_map(repo):
    """{path: (mode, sha)} for HEAD's tree ({} on an unborn branch)."""
    sha = repo.head_sha()
    if not sha:
        return {}
    return flatten_tree(repo, repo.read_commit(sha).tree)


def write_tree(repo, index):
    """Write tree objects for the stage-0 entries of ``index``; return the root tree sha."""
    if index.has_conflicts():
        raise Fatal("error: unmerged entries in index; cannot write tree")
    root = {}
    for e in index.stage0():
        parts = e.path.split("/")
        node = root
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = e

    def emit(node):
        ents = []
        for name, v in node.items():
            if isinstance(v, dict):
                ents.append((0o40000, name, emit(v)))
            else:
                ents.append((v.mode, name, v.sha))
        return repo.odb.write("tree", build_tree(ents))

    return emit(root)


def index_from_tree(repo, tree_sha):
    """Fresh Index (no stat data) containing the files of ``tree_sha``."""
    idx = Index(Index.path_for(repo))
    for path, (mode, sha) in flatten_tree(repo, tree_sha).items():
        idx._put(IndexEntry(path, sha, mode))
    return idx
