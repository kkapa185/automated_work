"""Single-file persistent storage.

File layout (all integers little-endian):
    magic    8 bytes  b'DB1000\\x01\\n'
    frame*   each: type u8 | payload length u32 | crc32(payload) u32 | payload
Frame types: 1 = SNAPSHOT (complete database image, always the first frame), 2 = DELTA (the net row
changes of one committed transaction). A commit appends one DELTA frame; a schema change (or a large log)
rewrites the file as a fresh SNAPSHOT via write-temp + fsync + atomic rename. On open, frames are replayed
in order and a torn / corrupt tail (crash mid-append) is discarded and truncated.
Payload encoding: unsigned LEB128 varints, zig-zag varints for signed integers, length-prefixed UTF-8 text.
Values: tag byte 0 NULL | 1 INTEGER (zig-zag varint) | 2 REAL (8-byte IEEE) | 3 TEXT | 4 BLOB.
"""
import os
import struct
import time
import zlib
from .errors import SqlError

MAGIC = b'DB1000\x01\n'
SNAPSHOT = 1
DELTA = 2
HDR = struct.Struct('<BII')
KINDS = {'table': 0, 'index': 1, 'view': 2, 'trigger': 3}
KIND_NAMES = {v: k for k, v in KINDS.items()}


class Writer:
    def __init__(self):
        self.b = bytearray()

    def varint(self, n):
        b = self.b
        while n >= 0x80:
            b.append((n & 0x7f) | 0x80)
            n >>= 7
        b.append(n)

    def zigzag(self, n):
        self.varint((n << 1) if n >= 0 else ((-n << 1) - 1))

    def text(self, s):
        d = s.encode('utf-8', 'surrogateescape')
        self.varint(len(d))
        self.b += d

    def value(self, v):
        t = type(v)
        b = self.b
        if v is None:
            b.append(0)
        elif t is int:
            b.append(1)
            self.zigzag(v)
        elif t is float:
            b.append(2)
            b += struct.pack('<d', v)
        elif t is str:
            b.append(3)
            self.text(v)
        else:
            b.append(4)
            self.varint(len(v))
            b += v


class Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def byte(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def varint(self):
        n = 0
        shift = 0
        while True:
            c = self.d[self.p]
            self.p += 1
            n |= (c & 0x7f) << shift
            if c < 0x80:
                return n
            shift += 7

    def zigzag(self):
        z = self.varint()
        return (z >> 1) if not z & 1 else -((z + 1) >> 1)

    def text(self):
        n = self.varint()
        s = self.d[self.p:self.p + n].decode('utf-8', 'surrogateescape')
        self.p += n
        return s

    def value(self):
        t = self.byte()
        if t == 0:
            return None
        if t == 1:
            return self.zigzag()
        if t == 2:
            v = struct.unpack_from('<d', self.d, self.p)[0]
            self.p += 8
            return v
        if t == 3:
            return self.text()
        n = self.varint()
        v = bytes(self.d[self.p:self.p + n])
        self.p += n
        return v


class Store:
    def __init__(self, path):
        self.path = path
        self.f = None
        self.log_bytes = 0
        self.snap_bytes = 0
        self.has_file = False
        self.saved_user_version = 0
        self.last_sync = 0.0
        self.unsynced = False

    # ------------------------------------------------------------ load
    def load(self, engine):
        path = self.path
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            return
        except IsADirectoryError:
            raise SqlError('unable to open database file')
        except OSError:
            raise SqlError('unable to open database file')
        if not data:
            return
        if data[:len(MAGIC)] != MAGIC:
            raise SqlError('file is not a database')
        pos = len(MAGIC)
        good = pos
        n = len(data)
        first = True
        engine.loading = True
        try:
            while pos + HDR.size <= n:
                typ, ln, crc = HDR.unpack_from(data, pos)
                start = pos + HDR.size
                if start + ln > n:
                    break
                payload = data[start:start + ln]
                if zlib.crc32(payload) != crc:
                    break
                if first:
                    if typ != SNAPSHOT:
                        raise SqlError('file is not a database')
                    self.apply_snapshot(engine, payload)
                    self.snap_bytes = HDR.size + ln
                    first = False
                elif typ == DELTA:
                    self.apply_delta(engine, payload)
                    self.log_bytes += HDR.size + ln
                else:
                    break
                pos = start + ln
                good = pos
        finally:
            engine.loading = False
        if first:
            raise SqlError('file is not a database')
        self.has_file = True
        self.saved_user_version = engine.db.user_version
        if good < n:
            with open(path, 'r+b') as f:
                f.truncate(good)

    def apply_snapshot(self, engine, payload):
        from .parser import Parser
        db = engine.db
        r = Reader(payload)
        db.user_version = r.varint()
        next_root = r.varint()
        nobj = r.varint()
        for _ in range(nobj):
            kind = KIND_NAMES[r.byte()]
            sql = r.text()
            root = r.varint()
            nauto = r.varint()
            autos = [r.varint() for _ in range(nauto)]
            stmt = Parser(sql).parse_statement()
            engine.ctx = None
            from .query import Ctx
            engine.ctx = Ctx(db)
            engine.execute_stored(stmt)
            obj = db.objects[-1]
            obj.rootpage = root
            if kind == 'table':
                for ix, rp in zip([i for i in obj.indexes if i.auto], autos):
                    ix.rootpage = rp
        db.next_root = next_root
        ntab = r.varint()
        for _ in range(ntab):
            name = r.text()
            seq = r.varint()
            nrows = r.varint()
            t = db.tables[name.lower()]
            t.seq = seq
            nc = len(t.columns)
            for _r in range(nrows):
                rid = r.zigzag()
                row = [r.value() for _c in range(nc)]
                row.append(rid)
                t._add(rid, row)
        db.undo.clear()

    def apply_delta(self, engine, payload):
        db = engine.db
        r = Reader(payload)
        db.user_version = r.varint()
        nops = r.varint()
        for _ in range(nops):
            op = r.byte()
            t = db.tables[r.text().lower()]
            if op == 1:
                rid = r.zigzag()
                row = [r.value() for _c in range(len(t.columns))]
                row.append(rid)
                if rid in t.rows:
                    t._replace(rid, row)
                else:
                    t._add(rid, row)
            elif op == 2:
                rid = r.zigzag()
                if rid in t.rows:
                    t._remove(rid)
            else:
                t.seq = r.varint()

    # ------------------------------------------------------------ write
    def encode_snapshot(self, db):
        w = Writer()
        w.varint(db.user_version)
        w.varint(db.next_root)
        w.varint(len(db.objects))
        tables = []
        for o in db.objects:
            w.b.append(KINDS[o.type])
            w.text(o.sql)
            w.varint(o.rootpage)
            if o.type == 'table':
                autos = [i for i in o.indexes if i.auto]
                w.varint(len(autos))
                for i in autos:
                    w.varint(i.rootpage)
                tables.append(o)
            else:
                w.varint(0)
        w.varint(len(tables))
        for t in tables:
            w.text(t.name)
            w.varint(t.seq)
            w.varint(len(t.rows))
            nc = len(t.columns)
            for rid, row in t.scan().items():
                w.zigzag(rid)
                for i in range(nc):
                    w.value(row[i])
        return bytes(w.b)

    def encode_delta(self, engine):
        db = engine.db
        touched = {}
        seqs = {}
        for e in db.undo:
            k = e[0]
            if k in ('ins', 'del', 'upd'):
                touched[(id(e[1]), e[2])] = (e[1], e[2])
            elif k == 'seq':
                seqs[id(e[1])] = e[1]
        w = Writer()
        w.varint(db.user_version)
        w.varint(len(touched) + len(seqs))
        for t, rid in touched.values():
            row = t.rows.get(rid)
            if row is None:
                w.b.append(2)
                w.text(t.name)
                w.zigzag(rid)
            else:
                w.b.append(1)
                w.text(t.name)
                w.zigzag(rid)
                for i in range(len(t.columns)):
                    w.value(row[i])
        for t in seqs.values():
            w.b.append(3)
            w.text(t.name)
            w.varint(t.seq)
        return bytes(w.b)

    def commit(self, engine):
        db = engine.db
        need_snapshot = not self.has_file or db.user_version != self.saved_user_version or \
            any(e[0] in ('schema', 'tstate') for e in db.undo) or \
            self.log_bytes > max(1 << 20, 2 * self.snap_bytes)
        if need_snapshot:
            self.write_snapshot(db)
        else:
            payload = self.encode_delta(engine)
            frame = HDR.pack(DELTA, len(payload), zlib.crc32(payload)) + payload
            if self.f is None:
                self.f = open(self.path, 'ab')
            try:
                self.f.write(frame)
                self.f.flush()
                self.unsynced = True
                now = time.time()
                if now - self.last_sync > 0.05:
                    os.fsync(self.f.fileno())
                    self.last_sync = now
                    self.unsynced = False
            except OSError as e:
                raise SqlError('disk I/O error: %s' % e.strerror)
            self.log_bytes += len(frame)
        self.saved_user_version = db.user_version

    def write_snapshot(self, db):
        payload = self.encode_snapshot(db)
        frame = HDR.pack(SNAPSHOT, len(payload), zlib.crc32(payload)) + payload
        if self.f is not None:
            self.f.close()
            self.f = None
        tmp = '%s.tmp-%d' % (self.path, os.getpid())
        try:
            with open(tmp, 'wb') as f:
                f.write(MAGIC)
                f.write(frame)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            d = os.path.dirname(os.path.abspath(self.path))
            try:
                fd = os.open(d, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                pass
        except OSError as e:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise SqlError('disk I/O error: %s' % e.strerror)
        self.has_file = True
        self.snap_bytes = len(frame)
        self.log_bytes = 0
        self.last_sync = time.time()
        self.unsynced = False

    def close(self, engine):
        if self.f is not None:
            try:
                if self.unsynced:
                    os.fsync(self.f.fileno())
            finally:
                self.f.close()
                self.f = None
