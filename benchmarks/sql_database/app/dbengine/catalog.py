"""Schema objects (tables, indexes, views, triggers) and the in-memory database with an undo log."""
from operator import itemgetter
from .errors import SqlError
from .values import get_collation, type_affinity, INT_MAX

ROWID_NAMES = ('rowid', 'oid', '_rowid_')


class Column:
    __slots__ = ('name', 'decl', 'affinity', 'notnull', 'default', 'collate', 'generated', 'gen_stored',
                 'hidden', 'pk')

    def __init__(self, name, decl='', notnull=False, default=None, collate=None, pk=False):
        self.name = name
        self.decl = decl
        self.affinity = type_affinity(decl)
        self.notnull = notnull
        self.default = default
        self.collate = collate
        self.generated = None
        self.gen_stored = False
        self.hidden = False
        self.pk = pk


class Index:
    def __init__(self, name, table, fns, collations, unique, auto=False, pred=None, sql=None,
                 colnames=None, colidx=None):
        self.name = name
        self.table = table
        self.fns = fns                # callables(row) -> value
        self.collations = collations  # collation names (upper) per key column
        self.cks = [get_collation(c) if c else None for c in collations]
        self.unique = unique
        self.auto = auto
        self.pred = pred
        self.sql = sql
        self.colidx = colidx          # column positions when every key is a plain column, else None
        self.colnames = colnames or []
        self.rootpage = 0
        self.map = {}
        self.has_ck = any(self.cks)
        self.tbl_name = table.name

    @property
    def type(self):
        return 'index'

    def key(self, row):
        if self.pred is not None:
            from .values import truth
            if truth(self.pred(row)) is not True:
                return None
        vals = []
        for f, ck in zip(self.fns, self.cks):
            v = f(row)
            if v is None:
                return None
            if ck is not None and type(v) is str:
                v = ck(v)
            vals.append(v)
        return tuple(vals)

    def lookup_key(self, vals):
        out = []
        for v, ck in zip(vals, self.cks):
            if ck is not None and type(v) is str:
                v = ck(v)
            out.append(v)
        return tuple(out)

    def add(self, row, rowid):
        k = self.key(row)
        if k is None:
            return
        if self.unique:
            self.map[k] = rowid
        else:
            d = self.map.get(k)
            if d is None:
                self.map[k] = {rowid: None}
            else:
                d[rowid] = None

    def remove(self, row, rowid):
        k = self.key(row)
        if k is None:
            return
        if self.unique:
            if self.map.get(k) == rowid:
                del self.map[k]
        else:
            d = self.map.get(k)
            if d is not None:
                d.pop(rowid, None)
                if not d:
                    del self.map[k]

    def rowids(self, k):
        v = self.map.get(k)
        if v is None:
            return []
        if self.unique:
            return [v]
        return sorted(v)


class Table:
    type = 'table'

    def __init__(self, name, columns):
        self.name = name
        self.tbl_name = name
        self.columns = columns
        self.rows = {}
        self.ordered = True
        self.max_rowid = 0
        self.indexes = []
        self.rowid_col = None      # index of INTEGER PRIMARY KEY column
        self.autoinc = False
        self.seq = 0
        self.checks = []           # (ast, text, name)
        self.pk_cols = []
        self.without_rowid = False
        self.sql = None
        self.rootpage = 0
        self.db = None
        self.compiled = None       # cached compiled constraint info
        self.virtual = False
        self.version = 0
        self.refresh_names()

    def refresh_names(self):
        self.colmap = {}
        for i, c in enumerate(self.columns):
            self.colmap.setdefault(c.name.lower(), i)

    @property
    def ncols(self):
        return len(self.columns)

    def col_index(self, name):
        return self.colmap.get(name.lower())

    # -------------------------------------------------------------- row storage
    def next_rowid(self):
        m = self.max_rowid
        if m is None:
            if not self.rows:
                m = 0
            elif self.ordered:
                m = next(reversed(self.rows))
            else:
                m = max(self.rows)
            self.max_rowid = m
        if self.autoinc and self.seq > m:
            m = self.seq
        if m >= INT_MAX:
            # find an unused rowid
            import random
            for _ in range(1000):
                r = random.randint(1, INT_MAX)
                if r not in self.rows:
                    return r
            raise SqlError('database or disk is full')
        return m + 1

    def scan(self):
        if not self.ordered:
            self.rows = dict(sorted(self.rows.items()))
            self.ordered = True
        return self.rows

    def _add(self, rowid, row):
        self.version += 1
        rows = self.rows
        if rows and self.ordered:
            m = self.max_rowid
            if m is None:
                m = next(reversed(rows))
            if rowid < m:
                self.ordered = False
        rows[rowid] = row
        if self.max_rowid is not None and rowid > self.max_rowid:
            self.max_rowid = rowid
        for ix in self.indexes:
            ix.add(row, rowid)

    def _remove(self, rowid):
        self.version += 1
        row = self.rows.pop(rowid)
        if rowid == self.max_rowid:
            self.max_rowid = None
        for ix in self.indexes:
            ix.remove(row, rowid)
        return row

    def _replace(self, rowid, newrow):
        self.version += 1
        old = self.rows[rowid]
        for ix in self.indexes:
            ix.remove(old, rowid)
        self.rows[rowid] = newrow
        for ix in self.indexes:
            ix.add(newrow, rowid)
        return old

    def insert_row(self, rowid, row):
        self._add(rowid, row)
        self.db.undo.append(('ins', self, rowid))

    def delete_row(self, rowid):
        row = self._remove(rowid)
        self.db.undo.append(('del', self, rowid, row))
        return row

    def update_row(self, rowid, newrow):
        old = self._replace(rowid, newrow)
        self.db.undo.append(('upd', self, rowid, old))

    def set_seq(self, v):
        self.db.undo.append(('seq', self, self.seq))
        self.seq = v

    def conflicts(self, row, rowid, exclude=None):
        """List of (existing_rowid, label) for every uniqueness violation of inserting row."""
        out = []
        if rowid in self.rows and rowid != exclude:
            out.append((rowid, None))
        for ix in self.indexes:
            if ix.unique:
                k = ix.key(row)
                if k is not None:
                    r = ix.map.get(k)
                    if r is not None and r != exclude:
                        out.append((r, ix))
        return out

    def rebuild_indexes(self):
        for ix in self.indexes:
            ix.map = {}
            for rid, row in self.rows.items():
                ix.add(row, rid)

    def snapshot(self):
        return (list(self.columns), dict(self.rows), self.ordered, self.max_rowid, list(self.indexes),
                self.rowid_col, self.autoinc, self.seq, list(self.checks), list(self.pk_cols), self.sql,
                self.name, {id(ix): (dict(ix.map)) for ix in self.indexes}, self.compiled)

    def restore(self, snap):
        (cols, rows, ordered, maxr, idxs, rc, ai, seq, checks, pkc, sql, name, maps, comp) = snap
        self.columns = cols
        self.rows = rows
        self.ordered = ordered
        self.max_rowid = maxr
        self.indexes = idxs
        self.rowid_col = rc
        self.autoinc = ai
        self.seq = seq
        self.checks = checks
        self.pk_cols = pkc
        self.sql = sql
        self.name = name
        self.tbl_name = name
        for ix in idxs:
            ix.map = maps[id(ix)]
            ix.tbl_name = name
        self.compiled = comp
        self.version += 1
        self.refresh_names()


class View:
    type = 'view'

    def __init__(self, name, select, cols, sql):
        self.name = name
        self.tbl_name = name
        self.select = select
        self.cols = cols
        self.sql = sql
        self.rootpage = 0


class Trigger:
    type = 'trigger'

    def __init__(self, name, table, stmt, sql):
        self.name = name
        self.tbl_name = table
        self.stmt = stmt
        self.sql = sql
        self.rootpage = 0


class Database:
    def __init__(self):
        self.tables = {}
        self.views = {}
        self.indexes = {}
        self.triggers = {}
        self.objects = []          # creation order
        self.next_root = 2
        self.undo = []
        self.last_insert_rowid = 0
        self.changes = 0
        self.total_changes = 0
        self.user_version = 0
        self.dirty = False

    # -------------------------------------------------------------- lookup
    def find_relation(self, name):
        ln = name.lower()
        t = self.tables.get(ln)
        if t is not None:
            return t
        v = self.views.get(ln)
        if v is not None:
            return v
        if ln in ('sqlite_master', 'sqlite_schema', 'sqlite_temp_master', 'sqlite_temp_schema'):
            return self.schema_table(ln)
        return None

    def name_in_use(self, name):
        ln = name.lower()
        if ln in self.tables:
            return 'table'
        if ln in self.views:
            return 'view'
        if ln in self.indexes:
            return 'index'
        return None

    def schema_table(self, ln):
        cols = [Column('type', 'text'), Column('name', 'text'), Column('tbl_name', 'text'),
                Column('rootpage', 'integer'), Column('sql', 'text')]
        t = Table('sqlite_master' if 'master' in ln else 'sqlite_schema', cols)
        t.db = self
        t.virtual = True
        rid = 0
        for o in self.objects:
            if o.type == 'table':
                rid += 1
                t.rows[rid] = ['table', o.name, o.name, o.rootpage, o.sql, rid]
                for ix in o.indexes:
                    if ix.auto:
                        rid += 1
                        t.rows[rid] = ['index', ix.name, o.name, ix.rootpage, None, rid]
            else:
                rid += 1
                t.rows[rid] = [o.type, o.name, o.tbl_name, o.rootpage, o.sql, rid]
        return t

    # -------------------------------------------------------------- undo log
    def log_schema(self):
        self.undo.append(('schema', dict(self.tables), dict(self.views), dict(self.indexes),
                          dict(self.triggers), list(self.objects), self.next_root))

    def log_table_state(self, table):
        self.undo.append(('tstate', table, table.snapshot()))

    def rollback_to(self, mark):
        undo = self.undo
        while len(undo) > mark:
            e = undo.pop()
            k = e[0]
            if k == 'ins':
                e[1]._remove(e[2])
            elif k == 'del':
                e[1]._add(e[2], e[3])
            elif k == 'upd':
                e[1]._replace(e[2], e[3])
            elif k == 'seq':
                e[1].seq = e[2]
            elif k == 'schema':
                (self.tables, self.views, self.indexes, self.triggers, self.objects, self.next_root) = e[1:]
            elif k == 'tstate':
                e[1].restore(e[2])
            elif k == 'uv':
                self.user_version = e[1]
