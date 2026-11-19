"""Object database: loose objects, pack files (idx v2, OFS/REF deltas), parsers."""
import hashlib
import mmap
import os
import struct
import tempfile
import zlib

from .util import fsdecode, fsencode

TYPE_NUM = {1: "commit", 2: "tree", 3: "blob", 4: "tag"}
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class ObjectNotFound(KeyError):
    pass


class CorruptObject(Exception):
    pass


def hash_object(type_, data):
    h = hashlib.sha1(b"%s %d\0" % (type_.encode(), len(data)))
    h.update(data)
    return h.hexdigest()


def apply_delta(base, delta):
    pos = 0

    def varint():
        nonlocal pos
        result = shift = 0
        while True:
            c = delta[pos]
            pos += 1
            result |= (c & 0x7F) << shift
            shift += 7
            if not c & 0x80:
                return result

    src_size = varint()
    dst_size = varint()
    if src_size != len(base):
        raise CorruptObject("delta base size mismatch")
    out = []
    n = len(delta)
    while pos < n:
        cmd = delta[pos]
        pos += 1
        if cmd & 0x80:
            off = size = 0
            for i in range(4):
                if cmd & (1 << i):
                    off |= delta[pos] << (8 * i)
                    pos += 1
            for i in range(3):
                if cmd & (0x10 << i):
                    size |= delta[pos] << (8 * i)
                    pos += 1
            if size == 0:
                size = 0x10000
            out.append(base[off:off + size])
        elif cmd:
            out.append(delta[pos:pos + cmd])
            pos += cmd
        else:
            raise CorruptObject("invalid delta opcode 0")
    res = b"".join(out)
    if len(res) != dst_size:
        raise CorruptObject("delta result size mismatch")
    return res


class Pack:
    def __init__(self, idx_path):
        self.idx_path = idx_path
        self.pack_path = idx_path[:-4] + ".pack"
        with open(idx_path, "rb") as f:
            self.idx = f.read()
        if self.idx[:4] != b"\xfftOc" or struct.unpack(">I", self.idx[4:8])[0] != 2:
            raise CorruptObject("unsupported pack index: " + idx_path)
        self.fanout = struct.unpack(">256I", self.idx[8:8 + 1024])
        self.n = self.fanout[255]
        self.sha_off = 8 + 1024
        self.ofs_off = self.sha_off + 24 * self.n
        self.big_off = self.ofs_off + 4 * self.n
        self._f = open(self.pack_path, "rb")
        self.data = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)

    def _sha_at(self, i):
        o = self.sha_off + i * 20
        return self.idx[o:o + 20]

    def _offset(self, i):
        v = struct.unpack(">I", self.idx[self.ofs_off + 4 * i:self.ofs_off + 4 * i + 4])[0]
        if v & 0x80000000:
            j = v & 0x7FFFFFFF
            v = struct.unpack(">Q", self.idx[self.big_off + 8 * j:self.big_off + 8 * j + 8])[0]
        return v

    def _lower_bound(self, key):
        b = key[0]
        lo = self.fanout[b - 1] if b else 0
        hi = self.fanout[b]
        while lo < hi:
            mid = (lo + hi) // 2
            if self._sha_at(mid) < key:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def find(self, binsha):
        i = self._lower_bound(binsha)
        if i < self.n and self._sha_at(i) == binsha:
            return self._offset(i)
        return None

    def prefix_matches(self, hexprefix):
        padded = hexprefix + "0" * (40 - len(hexprefix))
        key = bytes.fromhex(padded)
        i = self._lower_bound(key)
        res = []
        while i < self.n:
            h = self._sha_at(i).hex()
            if not h.startswith(hexprefix):
                break
            res.append(h)
            i += 1
        return res

    def all_shas(self):
        return [self._sha_at(i).hex() for i in range(self.n)]

    def _inflate(self, pos, size):
        d = zlib.decompressobj()
        parts = []
        chunk = max(4096, size + 64)
        while not d.eof:
            buf = self.data[pos:pos + chunk]
            if not buf:
                raise CorruptObject("truncated pack entry")
            parts.append(d.decompress(buf))
            pos += len(buf)
        res = b"".join(parts)
        if len(res) != size:
            raise CorruptObject("pack entry size mismatch")
        return res

    def read_at(self, offset, store):
        chain = []
        while True:
            data = self.data
            c = data[offset]
            pos = offset + 1
            t = (c >> 4) & 7
            size = c & 15
            shift = 4
            while c & 0x80:
                c = data[pos]
                pos += 1
                size |= (c & 0x7F) << shift
                shift += 7
            if t in TYPE_NUM:
                base = self._inflate(pos, size)
                btype = TYPE_NUM[t]
                break
            if t == OBJ_OFS_DELTA:
                c = data[pos]
                pos += 1
                off = c & 0x7F
                while c & 0x80:
                    c = data[pos]
                    pos += 1
                    off = ((off + 1) << 7) | (c & 0x7F)
                chain.append(self._inflate(pos, size))
                offset -= off
            elif t == OBJ_REF_DELTA:
                basesha = data[pos:pos + 20].hex()
                pos += 20
                chain.append(self._inflate(pos, size))
                btype, base = store.read(basesha)
                break
            else:
                raise CorruptObject("bad pack object type %d" % t)
        for delta in reversed(chain):
            base = apply_delta(base, delta)
        return btype, base


class ObjectStore:
    def __init__(self, objdir):
        self.objdir = objdir
        self._packs = None
        self._alts = None
        self._cache = {}

    # -- pack / alternates discovery
    def packs(self):
        if self._packs is None:
            self._packs = []
            pdir = os.path.join(self.objdir, "pack")
            try:
                names = sorted(os.listdir(pdir))
            except OSError:
                names = []
            for n in names:
                if n.endswith(".idx") and os.path.exists(os.path.join(pdir, n[:-4] + ".pack")):
                    try:
                        self._packs.append(Pack(os.path.join(pdir, n)))
                    except (OSError, CorruptObject):
                        pass
        return self._packs

    def alternates(self):
        if self._alts is None:
            self._alts = []
            try:
                with open(os.path.join(self.objdir, "info", "alternates"), "rb") as f:
                    for line in f.read().splitlines():
                        line = fsdecode(line).strip()
                        if line and not line.startswith("#"):
                            self._alts.append(ObjectStore(os.path.normpath(os.path.join(self.objdir, line))))
            except OSError:
                pass
        return self._alts

    def refresh(self):
        self._packs = None

    def loose_path(self, hexsha):
        return os.path.join(self.objdir, hexsha[:2], hexsha[2:])

    # -- reading
    def _read_local(self, hexsha):
        try:
            with open(self.loose_path(hexsha), "rb") as f:
                raw = zlib.decompress(f.read())
            nul = raw.index(b"\0")
            typ, size = raw[:nul].split(b" ")
            body = raw[nul + 1:]
            if int(size) != len(body):
                raise CorruptObject("loose object %s is corrupt" % hexsha)
            return typ.decode(), body
        except FileNotFoundError:
            pass
        except (zlib.error, ValueError):
            raise CorruptObject("loose object %s is corrupt" % hexsha)
        binsha = bytes.fromhex(hexsha)
        for p in self.packs():
            off = p.find(binsha)
            if off is not None:
                return p.read_at(off, self)
        return None

    def read(self, hexsha):
        hexsha = hexsha.lower()
        r = self._cache.get(hexsha)
        if r is not None:
            return r
        r = self._read_local(hexsha)
        if r is None:
            self.refresh()
            r = self._read_local(hexsha)
        if r is None:
            for a in self.alternates():
                try:
                    r = a.read(hexsha)
                    break
                except ObjectNotFound:
                    pass
        if r is None:
            raise ObjectNotFound(hexsha)
        if len(self._cache) > 512:
            self._cache.clear()
        if len(r[1]) < 1 << 20:
            self._cache[hexsha] = r
        return r

    def exists(self, hexsha):
        try:
            self.read(hexsha)
            return True
        except ObjectNotFound:
            return False

    def has_packed_or_loose(self, hexsha):
        if os.path.exists(self.loose_path(hexsha)):
            return True
        b = bytes.fromhex(hexsha)
        return any(p.find(b) is not None for p in self.packs())

    # -- writing
    def write(self, type_, data):
        hexsha = hash_object(type_, data)
        if self.has_packed_or_loose(hexsha):
            return hexsha
        path = self.loose_path(hexsha)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = zlib.compress(b"%s %d\0" % (type_.encode(), len(data)) + data, 1)
        fd, tmp = tempfile.mkstemp(dir=self.objdir, prefix="tmp_obj_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            os.chmod(tmp, 0o444)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return hexsha

    # -- abbreviation support
    def find_prefix(self, hexprefix):
        found = set()
        if len(hexprefix) >= 2:
            d = os.path.join(self.objdir, hexprefix[:2])
            try:
                for n in os.listdir(d):
                    if len(n) == 38 and n.startswith(hexprefix[2:]):
                        found.add(hexprefix[:2] + n)
            except OSError:
                pass
        for p in self.packs():
            found.update(p.prefix_matches(hexprefix))
        for a in self.alternates():
            found.update(a.find_prefix(hexprefix))
        return sorted(found)

    def approx_count(self):
        n = 0
        try:
            for d in os.listdir(self.objdir):
                if len(d) == 2:
                    try:
                        n += len(os.listdir(os.path.join(self.objdir, d)))
                    except OSError:
                        pass
        except OSError:
            pass
        n += sum(p.n for p in self.packs())
        return n

    def default_abbrev(self):
        count = self.approx_count()
        length = (count.bit_length() + 1) // 2  # ceil((msb index + 1) / 2)
        return max(7, length)

    def shorten(self, hexsha, minlen=None):
        if minlen is None:
            minlen = self.default_abbrev()
        for n in range(max(4, minlen), 40):
            if len(self.find_prefix(hexsha[:n])) <= 1:
                return hexsha[:n]
        return hexsha


# ---------------------------------------------------------------- parsers

def parse_tree(data):
    """Return list of (mode:int, name:str, hexsha)."""
    i = 0
    ents = []
    n = len(data)
    while i < n:
        sp = data.index(b" ", i)
        mode = int(data[i:sp], 8)
        nul = data.index(b"\0", sp)
        name = fsdecode(data[sp + 1:nul])
        ents.append((mode, name, data[nul + 1:nul + 21].hex()))
        i = nul + 21
    return ents


def tree_sort_key(entry):
    mode, name = entry[0], entry[1]
    k = fsencode(name)
    return k + b"/" if mode == 0o40000 else k


def build_tree(entries):
    out = []
    for mode, name, sha in sorted(entries, key=tree_sort_key):
        out.append(b"%o %s\0" % (mode, fsencode(name)) + bytes.fromhex(sha))
    return b"".join(out)


def mode_type(mode):
    if mode == 0o40000:
        return "tree"
    if mode == 0o160000:
        return "commit"
    return "blob"


class Commit:
    def __init__(self, tree, parents, author, committer, message, extra=None):
        self.tree = tree
        self.parents = parents
        self.author = author
        self.committer = committer
        self.message = message
        self.extra = extra or []

    def serialize(self):
        lines = ["tree " + self.tree]
        lines += ["parent " + p for p in self.parents]
        lines.append("author " + self.author)
        lines.append("committer " + self.committer)
        for k, v in self.extra:
            lines.append(k + " " + v.replace("\n", "\n "))
        return fsencode("\n".join(lines) + "\n\n" + self.message)


def parse_commit(data):
    text = fsdecode(data)
    if "\n\n" in text:
        head, message = text.split("\n\n", 1)
    else:
        head, message = text.rstrip("\n"), ""
    tree = None
    parents = []
    author = committer = ""
    extra = []
    cur = None
    for line in head.split("\n"):
        if line.startswith(" ") and cur is not None:
            extra[cur] = (extra[cur][0], extra[cur][1] + "\n" + line[1:])
            continue
        key, _, val = line.partition(" ")
        if key == "tree":
            tree = val
        elif key == "parent":
            parents.append(val)
        elif key == "author":
            author = val
        elif key == "committer":
            committer = val
        else:
            extra.append((key, val))
            cur = len(extra) - 1
    return Commit(tree, parents, author, committer, message, extra)


class Tag:
    def __init__(self, object_, type_, name, tagger, message):
        self.object = object_
        self.type = type_
        self.name = name
        self.tagger = tagger
        self.message = message

    def serialize(self):
        s = "object %s\ntype %s\ntag %s\n" % (self.object, self.type, self.name)
        if self.tagger:
            s += "tagger %s\n" % self.tagger
        return fsencode(s + "\n" + self.message)


def parse_tag(data):
    text = fsdecode(data)
    head, _, message = text.partition("\n\n")
    f = {}
    for line in head.split("\n"):
        k, _, v = line.partition(" ")
        f[k] = v
    return Tag(f.get("object"), f.get("type"), f.get("tag"), f.get("tagger"), message)


def parse_ident(s):
    """'Name <email> 1700000000 +0000' -> (name, email, ts, tz_str)."""
    lt = s.find("<")
    gt = s.rfind(">")
    if lt < 0 or gt < lt:
        return s, "", 0, "+0000"
    name = s[:lt].rstrip()
    email = s[lt + 1:gt]
    rest = s[gt + 1:].split()
    ts = int(rest[0]) if rest and rest[0].lstrip("-").isdigit() else 0
    tz = rest[1] if len(rest) > 1 else "+0000"
    return name, email, ts, tz
