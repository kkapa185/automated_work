"""Statement execution: DDL, DML, transactions, PRAGMA."""
from operator import itemgetter
from .errors import SqlError
from .catalog import Database, Table, Column, Index, View, Trigger, ROWID_NAMES
from .parser import Parser
from . import values as V
from .values import truth, apply_affinity, type_affinity, get_collation
from .alter import AlterMixin
from .triggers import TriggerMixin
from .query import (Ctx, Comp, Scope, Source, compile_select, FromPlan, split_and, sort_rows)


class Result:
    def __init__(self, columns=None, rows=None):
        self.columns = columns or []
        self.rows = rows or []


class TInfo:
    """Compiled per-table information used by DML."""

    def __init__(self, table, ctx):
        self.scope = Scope(None)
        src = Source(table.name, [c.name for c in table.columns], [c.affinity for c in table.columns],
                     [c.collate for c in table.columns], table=table, has_rowid=True)
        self.scope.add(src)
        comp = Comp(ctx, self.scope)
        self.defaults = []
        for c in table.columns:
            if c.default is not None:
                self.defaults.append(comp.comp(c.default))
            else:
                self.defaults.append(None)
        self.gens = []
        for i, c in enumerate(table.columns):
            if c.generated is not None:
                self.gens.append((i, comp.comp(c.generated)))
        self.checks = [(comp.comp(e), text, name) for e, text, name in table.checks]
        self.notnull = [i for i, c in enumerate(table.columns) if c.notnull]


def prepend_source(node, target):
    if node[0] == 'join':
        return ('join', prepend_source(node[1], target), node[2], node[3], node[4], node[5], node[6])
    return ('join', target, node, 'CROSS', None, None, False)


class Engine(AlterMixin, TriggerMixin):
    def empty_result(self):
        return Result()

    def __init__(self, path=None):
        self.loading = False
        self.db = Database()
        self.path = path
        self.store = None
        self.in_txn = False
        self.savepoints = []       # (name, undo mark)
        self.txn_by_savepoint = False
        self.ctx = None
        if path is not None:
            try:
                from .storage import Store
            except ImportError:
                raise SqlError('persistent storage is not available in this build')
            self.store = Store(path)
            self.store.load(self)

    # ------------------------------------------------------------ driver
    def execute(self, stmt):
        t = stmt['type']
        db = self.db
        handler = getattr(self, 'x_' + t)
        if t in ('begin', 'commit', 'rollback', 'savepoint', 'release'):
            return handler(stmt)
        mark = len(db.undo)
        saved_counters = (db.last_insert_rowid, db.changes, db.total_changes)
        self.ctx = Ctx(db)
        try:
            res = handler(stmt)
        except BaseException as exc:
            db.rollback_to(mark)
            if getattr(exc, 'rollback', False):
                self.force_rollback = True
            if self.in_txn and getattr(self, 'force_rollback', False):
                self.force_rollback = False
                self.rollback_all()
            elif not self.in_txn:
                db.undo.clear()
            raise
        if not self.in_txn:
            self.commit_changes()
        return res

    def execute_stored(self, stmt):
        """Execute a stored schema statement while loading a database file (no commit)."""
        getattr(self, 'x_' + stmt['type'])(stmt)
        self.db.undo.clear()

    def commit_changes(self):
        db = self.db
        if self.store is not None and db.undo and not self.loading:
            try:
                self.store.commit(self)
            except BaseException:
                db.rollback_to(0)
                db.undo.clear()
                raise
        db.undo.clear()

    def rollback_all(self):
        self.db.rollback_to(0)
        self.db.undo.clear()
        self.in_txn = False
        self.savepoints = []
        self.txn_by_savepoint = False

    def close(self):
        if self.in_txn:
            self.rollback_all()
        if self.store is not None:
            self.store.close(self)

    # ------------------------------------------------------------ transactions
    def x_begin(self, st):
        if self.in_txn:
            raise SqlError('cannot start a transaction within a transaction')
        self.in_txn = True
        self.txn_by_savepoint = False
        self.savepoints = []
        return Result()

    def x_commit(self, st):
        if not self.in_txn:
            raise SqlError('cannot commit - no transaction is active')
        self.in_txn = False
        self.savepoints = []
        self.txn_by_savepoint = False
        self.commit_changes()
        return Result()

    def x_rollback(self, st):
        name = st['to']
        if name is None:
            if not self.in_txn:
                raise SqlError('cannot rollback - no transaction is active')
            self.rollback_all()
            return Result()
        for i in range(len(self.savepoints) - 1, -1, -1):
            if self.savepoints[i][0].lower() == name.lower():
                self.db.rollback_to(self.savepoints[i][1])
                del self.savepoints[i + 1:]
                return Result()
        raise SqlError('no such savepoint: %s' % name)

    def x_savepoint(self, st):
        if not self.in_txn:
            self.in_txn = True
            self.txn_by_savepoint = True
        self.savepoints.append((st['name'], len(self.db.undo)))
        return Result()

    def x_release(self, st):
        name = st['name']
        for i in range(len(self.savepoints) - 1, -1, -1):
            if self.savepoints[i][0].lower() == name.lower():
                del self.savepoints[i:]
                if not self.savepoints and self.txn_by_savepoint:
                    self.in_txn = False
                    self.txn_by_savepoint = False
                    self.commit_changes()
                return Result()
        raise SqlError('no such savepoint: %s' % name)

    def x_noop(self, st):
        return Result()

    # ------------------------------------------------------------ SELECT
    def x_select(self, st):
        plan = compile_select(st, self.ctx, None)
        return Result(list(plan.names), [tuple(r) for r in plan.iter()])

    # ------------------------------------------------------------ helpers
    def get_table(self, name, for_write=True):
        rel = self.db.find_relation(name)
        if rel is None:
            raise SqlError('no such table: %s' % name, 'parse')
        if isinstance(rel, View):
            raise SqlError('cannot modify %s because it is a view' % rel.name, 'parse')
        if rel.virtual:
            raise SqlError('table %s may not be modified' % rel.name, 'parse')
        return rel

    def tinfo(self, table):
        ti = table.compiled
        if ti is None:
            ti = table.compiled = TInfo(table, self.ctx)
        return ti

    def conflict_label(self, table, ix):
        if ix is None:
            if table.rowid_col is not None:
                return '%s.%s' % (table.name, table.columns[table.rowid_col].name)
            return '%s.rowid' % table.name
        return ', '.join(ix.colnames)

    def prepare_row(self, table, ti, row, action):
        """Apply affinity / generated columns; run NOT NULL and CHECK. Returns False if row is to be ignored."""
        cols = table.columns
        for i, c in enumerate(cols):
            v = row[i]
            if v is not None and c.affinity != 'BLOB':
                row[i] = apply_affinity(v, c.affinity)
        for i, fn in ti.gens:
            row[i] = apply_affinity(fn(row), cols[i].affinity)
        for i in ti.notnull:
            if row[i] is None:
                if action == 'IGNORE':
                    return False
                if action == 'REPLACE' and ti.defaults[i] is not None:
                    d = apply_affinity(ti.defaults[i]([]), cols[i].affinity)
                    if d is not None:
                        row[i] = d
                        continue
                raise SqlError('NOT NULL constraint failed: %s.%s' % (table.name, cols[i].name))
        for fn, text, name in ti.checks:
            v = fn(row)
            if v is not None and not truth(v):
                if action == 'IGNORE':
                    return False
                raise SqlError('CHECK constraint failed: %s' % (name or text))
        return True

    def assign_rowid(self, table, row):
        rc = table.rowid_col
        if rc is not None:
            v = row[rc]
            if v is None:
                rid = table.next_rowid()
                row[rc] = rid
                return rid
            if type(v) is not int:
                raise SqlError('datatype mismatch')
            return v
        return table.next_rowid()

    def finish_insert(self, table, rowid, row):
        table.insert_row(rowid, row)
        if table.autoinc and rowid > table.seq:
            table.set_seq(rowid)
        self.db.last_insert_rowid = rowid

    # ------------------------------------------------------------ INSERT
    def x_insert(self, st):
        db = self.db
        ctx = self.ctx
        pushed = False
        if st.get('with'):
            from .query import Cte
            rec, ctes = st['with']
            ctx.ctes.append({n.lower(): Cte(n, c, s, rec) for n, c, s in ctes})
        rel = db.find_relation(st['table'])
        if isinstance(rel, View):
            return self.view_insert(st, rel)
        table = self.get_table(st['table'])
        ti = self.tinfo(table)
        ncols = len(table.columns)
        colnames = [c.name for c in table.columns]
        action = st['action']
        if st['cols'] is not None:
            colpos = []
            for name in st['cols']:
                i = table.col_index(name)
                if i is None:
                    if name.lower() in ROWID_NAMES:
                        i = -1
                    else:
                        raise SqlError('table %s has no column named %s' % (table.name, name), 'parse')
                if i >= 0 and table.columns[i].generated is not None:
                    raise SqlError('cannot INSERT into generated column "%s"' % name, 'parse')
                colpos.append(i)
        else:
            colpos = [i for i, c in enumerate(table.columns) if c.generated is None and not c.hidden]
        if st['default_values']:
            source_rows = [[]]
            colpos = []
        else:
            plan = compile_select(st['source'], ctx, None)
            if plan.ncols != len(colpos):
                if st['cols'] is None:
                    raise SqlError('table %s has %d columns but %d values were supplied'
                                   % (table.name, len(colpos), plan.ncols), 'parse')
                raise SqlError('%d values for %d columns' % (plan.ncols, len(colpos)), 'parse')
            source_rows = plan.run()
        upserts = st['upserts']
        up_info = [self.compile_upsert(table, u) for u in upserts]
        alias = st['alias'] or table.name
        ret = None
        if st['returning']:
            ret = self.compile_returning(table, st['returning'], alias)
        out_rows = []
        count = 0
        defaults = ti.defaults
        n_with_rowid = ncols + 1
        for srow in source_rows:
            row = [None] * n_with_rowid
            given = [False] * ncols
            rowid_given = None
            for p, v in zip(colpos, srow):
                if p < 0:
                    rowid_given = v
                else:
                    row[p] = v
                    given[p] = True
            for i in range(ncols):
                if not given[i]:
                    d = defaults[i]
                    if d is not None:
                        row[i] = d([])
            if rowid_given is not None:
                rc = table.rowid_col
                if rc is not None:
                    row[rc] = rowid_given
                else:
                    iv = apply_affinity(rowid_given, 'INTEGER')
                    if type(iv) is not int:
                        raise SqlError('datatype mismatch')
                    rowid_given = iv
            if not self.prepare_row(table, ti, row, action):
                continue
            if rowid_given is not None and table.rowid_col is None:
                rowid = rowid_given
            else:
                rowid = self.assign_rowid(table, row)
            row[ncols] = rowid
            if db.triggers and not self.fire(table.name, colnames, 'BEFORE', 'INSERT', row, None):
                continue
            conflicts = table.conflicts(row, rowid)
            if conflicts:
                handled = False
                if up_info:
                    handled = self.handle_upsert(table, ti, row, rowid, conflicts, up_info, ret, out_rows)
                    if handled == 'counted':
                        count += 1
                        continue
                    if handled:
                        continue
                if action == 'IGNORE':
                    continue
                if action == 'REPLACE':
                    for crid, ix in conflicts:
                        if crid in table.rows:
                            table.delete_row(crid)
                else:
                    if action == 'ROLLBACK':
                        self.force_rollback = True
                    raise SqlError('UNIQUE constraint failed: %s' % self.conflict_label(table, conflicts[0][1]))
            self.finish_insert(table, rowid, row)
            count += 1
            if ret is not None:
                out_rows.append(tuple([f(row) for f in ret[1]]))
            if db.triggers:
                self.fire(table.name, colnames, 'AFTER', 'INSERT', row, None)
        db.changes = count
        db.total_changes += count
        if ret is not None:
            return Result(ret[0], out_rows)
        return Result()

    def compile_returning(self, table, cols, alias):
        from .query import star_items
        scope = Scope(None)
        src = Source(alias, [c.name for c in table.columns], [c.affinity for c in table.columns],
                     [c.collate for c in table.columns], table=table, has_rowid=True)
        scope.add(src)
        comp = Comp(self.ctx, scope)
        names = []
        fns = []
        for c in cols:
            if c[0] == 'star':
                for node, nm in star_items(scope, c[1]):
                    names.append(nm)
                    fns.append(comp.comp(node))
            else:
                _, e, al, text = c
                names.append(al if al else (e[2] if e[0] == 'col' else text))
                fns.append(comp.comp(e))
        return names, fns

    def compile_upsert(self, table, u):
        scope = Scope(None)
        cols = [c.name for c in table.columns]
        affs = [c.affinity for c in table.columns]
        colls = [c.collate for c in table.columns]
        scope.add(Source(table.name, cols, affs, colls, table=table, has_rowid=True))
        exc = Source('excluded', cols, affs, colls, table=table, has_rowid=True)
        exc.hidden = set(range(len(cols)))   # unqualified names refer to the target table
        scope.add(exc)
        comp = Comp(self.ctx, scope)
        info = {'u': u, 'target': None}
        if u['target'] is not None:
            names = []
            for e in u['target']:
                if e[0] != 'col':
                    raise SqlError('ON CONFLICT target must be a column list', 'parse')
                names.append(e[2].lower())
            info['target'] = names
        if u['do'] == 'UPDATE':
            sets = []
            for names, e in u['sets']:
                if len(names) != 1:
                    raise SqlError('multi-column assignment in upsert is not supported', 'parse')
                i = table.col_index(names[0])
                if i is None:
                    if names[0].lower() in ROWID_NAMES:
                        i = -1
                    else:
                        raise SqlError('no such column: %s' % names[0], 'parse')
                sets.append((i, comp.comp(e)))
            info['sets'] = sets
            info['where'] = comp.comp(u['where']) if u['where'] is not None else None
        if u['twhere'] is not None:
            info['twhere'] = comp.comp(u['twhere'])
        return info

    def handle_upsert(self, table, ti, row, rowid, conflicts, up_info, ret, out_rows):
        crid, ix = conflicts[0]
        for info in up_info:
            tgt = info['target']
            if tgt is not None:
                if ix is None:
                    rc = table.rowid_col
                    names = [table.columns[rc].name.lower()] if rc is not None else ['rowid']
                else:
                    names = [c.split('.', 1)[-1].lower() for c in ix.colnames]
                if sorted(tgt) != sorted(names):
                    continue
            u = info['u']
            if u['do'] == 'NOTHING':
                return True
            old = table.rows[crid]
            both = list(old) + list(row)
            if info['where'] is not None and not truth(info['where'](both)):
                return True
            new = list(old)
            newrid = crid
            for i, fn in info['sets']:
                v = fn(both)
                if i < 0:
                    iv = apply_affinity(v, 'INTEGER')
                    if type(iv) is not int:
                        raise SqlError('datatype mismatch')
                    newrid = iv
                else:
                    new[i] = v
            rc = table.rowid_col
            if rc is not None:
                if new[rc] is None:
                    new[rc] = newrid
                elif new[rc] != old[rc]:
                    iv = apply_affinity(new[rc], 'INTEGER')
                    if type(iv) is not int:
                        raise SqlError('datatype mismatch')
                    new[rc] = newrid = iv
                else:
                    newrid = new[rc]
            if not self.prepare_row(table, ti, new, 'ABORT'):
                return True
            new[len(table.columns)] = newrid
            confl = table.conflicts(new, newrid, exclude=crid)
            if confl:
                raise SqlError('UNIQUE constraint failed: %s' % self.conflict_label(table, confl[0][1]))
            if newrid == crid:
                table.update_row(crid, new)
            else:
                table.delete_row(crid)
                table.insert_row(newrid, new)
            self.db.last_insert_rowid = self.db.last_insert_rowid
            if ret is not None:
                out_rows.append(tuple([f(new) for f in ret[1]]))
            return 'counted'
        return False

    # ------------------------------------------------------------ UPDATE / DELETE
    def scan_matches(self, st, table, alias):
        """Plan the scan of target table (+ FROM sources). Returns (scope, rows iterator)."""
        scope = Scope(None)
        node = ('table', table.name, alias)
        if st.get('from') is not None:
            node = prepend_source(st['from'], node)
        fp = FromPlan(self.ctx, scope, node, st['where'])
        return scope, fp

    def ordered_limit(self, st, scope, rows):
        if st.get('order'):
            comp = Comp(self.ctx, scope)
            terms = []
            fns = []
            for e, desc, nulls in st['order']:
                fns.append(comp.comp(e))
                terms.append((desc, (nulls == 'FIRST') if nulls else None, None))
            items = [(r, [f(r) for f in fns]) for r in rows]
            sort_rows(items, terms)
            rows = [i[0] for i in items]
        if st.get('limit') is not None:
            from .query import eval_limit
            comp = Comp(self.ctx, Scope(None))
            lim = eval_limit(comp.comp(st['limit']))
            off = eval_limit(comp.comp(st['offset'])) if st.get('offset') is not None else 0
            rows = rows[max(off, 0):]
            if lim >= 0:
                rows = rows[:lim]
        return rows

    def x_update(self, st):
        db = self.db
        if st.get('with'):
            from .query import Cte
            rec, ctes = st['with']
            self.ctx.ctes.append({n.lower(): Cte(n, c, s, rec) for n, c, s in ctes})
        rel = db.find_relation(st['table'])
        if isinstance(rel, View):
            return self.view_update(st, rel)
        table = self.get_table(st['table'])
        ti = self.tinfo(table)
        colnames = [c.name for c in table.columns]
        alias = st['alias'] or table.name
        scope, fp = self.scan_matches(st, table, alias)
        comp = Comp(self.ctx, scope)
        ncols = len(table.columns)
        sets = []
        for names, e in st['sets']:
            if len(names) > 1:
                if e[0] != 'row' or len(e[1]) != len(names):
                    raise SqlError('number of columns on the left does not match the right', 'parse')
                pairs = list(zip(names, e[1]))
            else:
                pairs = [(names[0], e)]
            for nm, ex in pairs:
                i = table.col_index(nm)
                if i is None:
                    if nm.lower() in ROWID_NAMES:
                        i = -1
                    else:
                        raise SqlError('no such column: %s' % nm, 'parse')
                elif table.columns[i].generated is not None:
                    raise SqlError('cannot UPDATE generated column "%s"' % nm, 'parse')
                sets.append((i, comp.comp(ex)))
        assigned = {(table.columns[i].name.lower() if i >= 0 else 'rowid') for i, _ in sets}
        ret = self.compile_returning(table, st['returning'], alias) if st['returning'] else None
        rows = list(fp.iter())
        rows = self.ordered_limit(st, scope, rows)
        action = st['action']
        out_rows = []
        count = 0
        seen = set()
        for flat in rows:
            old = flat[:ncols + 1]
            rowid = old[ncols]
            if rowid in seen:
                continue
            seen.add(rowid)
            if rowid not in table.rows:
                continue
            new = list(old)
            newrid = rowid
            for i, fn in sets:
                v = fn(flat)
                if i < 0:
                    iv = apply_affinity(v, 'INTEGER')
                    if type(iv) is not int:
                        raise SqlError('datatype mismatch')
                    newrid = iv
                else:
                    new[i] = v
            rc = table.rowid_col
            if rc is not None:
                if new[rc] != old[rc] or newrid != rowid:
                    if newrid != rowid and new[rc] == old[rc]:
                        new[rc] = newrid
                    v = apply_affinity(new[rc], 'INTEGER')
                    if type(v) is not int:
                        raise SqlError('datatype mismatch')
                    new[rc] = newrid = v
            if not self.prepare_row(table, ti, new, action):
                continue
            new[ncols] = newrid
            confl = table.conflicts(new, newrid, exclude=rowid)
            if confl:
                if action == 'IGNORE':
                    continue
                if action == 'REPLACE':
                    for crid, ix in confl:
                        if crid in table.rows and crid != rowid:
                            table.delete_row(crid)
                else:
                    if action == 'ROLLBACK':
                        self.force_rollback = True
                    raise SqlError('UNIQUE constraint failed: %s' % self.conflict_label(table, confl[0][1]))
            if db.triggers and not self.fire(table.name, colnames, 'BEFORE', 'UPDATE', new, old, assigned):
                continue
            if newrid == rowid:
                table.update_row(rowid, new)
            else:
                table.delete_row(rowid)
                table.insert_row(newrid, new)
            count += 1
            if ret is not None:
                out_rows.append(tuple([f(new) for f in ret[1]]))
            if db.triggers:
                self.fire(table.name, colnames, 'AFTER', 'UPDATE', new, old, assigned)
        db.changes = count
        db.total_changes += count
        if ret is not None:
            return Result(ret[0], out_rows)
        return Result()

    def x_delete(self, st):
        db = self.db
        if st.get('with'):
            from .query import Cte
            rec, ctes = st['with']
            self.ctx.ctes.append({n.lower(): Cte(n, c, s, rec) for n, c, s in ctes})
        rel = db.find_relation(st['table'])
        if isinstance(rel, View):
            return self.view_delete(st, rel)
        table = self.get_table(st['table'])
        colnames = [c.name for c in table.columns]
        alias = st['alias'] or table.name
        scope, fp = self.scan_matches(st, table, alias)
        ncols = len(table.columns)
        ret = self.compile_returning(table, st['returning'], alias) if st['returning'] else None
        if st['where'] is None and not st.get('order') and st.get('limit') is None:
            rows = list(table.scan().values())
        else:
            rows = self.ordered_limit(st, scope, list(fp.iter()))
        out_rows = []
        count = 0
        for old in rows:
            rowid = old[ncols]
            if rowid not in table.rows:
                continue
            cur = table.rows[rowid]
            if db.triggers and not self.fire(table.name, colnames, 'BEFORE', 'DELETE', None, cur):
                continue
            table.delete_row(rowid)
            count += 1
            if ret is not None:
                out_rows.append(tuple([f(cur) for f in ret[1]]))
            if db.triggers:
                self.fire(table.name, colnames, 'AFTER', 'DELETE', None, cur)
        db.changes = count
        db.total_changes += count
        if ret is not None:
            return Result(ret[0], out_rows)
        return Result()

    # ------------------------------------------------------------ DDL
    def check_new_name(self, name, if_not_exists, kind):
        used = self.db.name_in_use(name)
        if name.lower().startswith('sqlite_'):
            raise SqlError('object name reserved for internal use: %s' % name, 'parse')
        if used is not None:
            if if_not_exists and (used == kind or True):
                return False
            if kind == 'index' and used != 'index':
                raise SqlError('there is already a %s named %s' % (used, name), 'parse')
            raise SqlError('%s %s already exists' % (used if kind != 'index' else 'index', name), 'parse')
        return True

    def new_root(self):
        r = self.db.next_root
        self.db.next_root += 1
        return r

    def x_create_table(self, st):
        db = self.db
        if not self.check_new_name(st['name'], st['if_not_exists'], 'table'):
            return Result()
        if st['select'] is not None:
            plan = compile_select(st['select'], self.ctx, None)
            rows = plan.run()
            names = list(plan.names)
            affs = [plan.out_affs[i] if hasattr(plan, 'out_affs') else None for i in range(len(names))]
            declmap = {'INTEGER': 'INT', 'TEXT': 'TEXT', 'REAL': 'REAL', 'NUMERIC': 'NUM', None: '', 'BLOB': ''}
            cols = [Column(n, declmap.get(a, '')) for n, a in zip(names, affs)]
            seen = set()
            for c in cols:
                if c.name.lower() in seen:
                    raise SqlError('duplicate column name: %s' % c.name, 'parse')
                seen.add(c.name.lower())
            sql = 'CREATE TABLE %s(%s)' % (st['name'], ','.join(
                c.name + (' ' + c.decl if c.decl else '') for c in cols))
            db.log_schema()
            t = Table(st['name'], cols)
            t.db = db
            t.sql = sql
            t.rootpage = self.new_root()
            db.tables[t.name.lower()] = t
            db.objects.append(t)
            for r in rows:
                rid = t.next_rowid()
                row = list(r)
                for i, c in enumerate(cols):
                    row[i] = apply_affinity(row[i], c.affinity)
                row.append(rid)
                t.insert_row(rid, row)
            return Result()
        table = self.build_table(st)
        db.log_schema()
        table.rootpage = self.new_root()
        db.tables[table.name.lower()] = table
        db.objects.append(table)
        for ix in table.indexes:
            ix.rootpage = self.new_root()
        if table.autoinc and 'sqlite_sequence' not in db.tables:
            pass
        return Result()

    def build_table(self, st):
        db = self.db
        cols = []
        pk_names = []
        pk_decl = 0
        seen = set()
        for cd in st['columns']:
            if cd['name'].lower() in seen:
                raise SqlError('duplicate column name: %s' % cd['name'], 'parse')
            seen.add(cd['name'].lower())
            c = Column(cd['name'], cd['type'], cd['notnull'], cd['default'], cd['collate'], cd['pk'])
            if cd['collate']:
                get_collation(cd['collate'])
            if cd['generated'] is not None:
                c.generated = cd['generated']
                c.gen_stored = cd.get('gen_stored', False)
            cols.append(c)
            if cd['pk']:
                pk_names.append(cd['name'])
                pk_decl += 1
        t = Table(st['name'], cols)
        t.db = db
        t.sql = st['schema_sql']
        t.without_rowid = st.get('without_rowid', False)
        autoinc = any(cd['autoinc'] for cd in st['columns'])
        uniques = []
        for cd in st['columns']:
            for e, text, name in cd['checks']:
                t.checks.append((e, text, name))
            if cd['unique']:
                uniques.append([(cd['name'], None)])
        for con in st['constraints']:
            k = con['kind']
            if k == 'pk':
                names = []
                for e, coll, desc, text in con['cols']:
                    if e[0] != 'col':
                        raise SqlError('expressions prohibited in PRIMARY KEY', 'parse')
                    names.append(e[2])
                pk_names = names
                pk_decl += 1
            elif k == 'unique':
                uniques.append([(e[2] if e[0] == 'col' else None, coll) for e, coll, desc, text in con['cols']])
            elif k == 'check':
                t.checks.append((con['expr'], con['text'], con['name']))
        if pk_decl > 1:
            raise SqlError('table "%s" has more than one primary key' % st['name'], 'parse')
        pk_pos = []
        for n in pk_names:
            i = t.col_index(n)
            if i is None:
                raise SqlError('table %s has no column named %s' % (st['name'], n), 'parse')
            pk_pos.append(i)
            t.columns[i].pk = True
        t.pk_cols = pk_pos
        if len(pk_pos) == 1 and cols[pk_pos[0]].decl.strip().upper() == 'INTEGER':
            t.rowid_col = pk_pos[0]
        if autoinc:
            if t.rowid_col is None:
                raise SqlError('AUTOINCREMENT is only allowed on an INTEGER PRIMARY KEY', 'parse')
            t.autoinc = True
        if t.without_rowid:
            if not pk_pos:
                raise SqlError('PRIMARY KEY missing on table %s' % st['name'], 'parse')
            for i in pk_pos:
                cols[i].notnull = True
        n = 0

        def add_auto(poss, colls):
            nonlocal n
            n += 1
            fns = [itemgetter(i) for i in poss]
            cn = [(colls[j] or cols[i].collate or '') for j, i in enumerate(poss)]
            ix = Index('sqlite_autoindex_%s_%d' % (t.name, n), t, fns, [c.upper() if c else None for c in cn],
                       True, auto=True, colnames=['%s.%s' % (t.name, cols[i].name) for i in poss], colidx=list(poss))
            t.indexes.append(ix)
        if pk_pos and t.rowid_col is None:
            add_auto(pk_pos, [None] * len(pk_pos))
        for u in uniques:
            poss = []
            colls = []
            for nm, coll in u:
                i = t.col_index(nm) if nm else None
                if i is None:
                    raise SqlError('table %s has no column named %s' % (st['name'], nm), 'parse')
                poss.append(i)
                colls.append(coll)
            add_auto(poss, colls)
        return t

    def x_create_index(self, st):
        db = self.db
        if not self.check_new_name(st['name'], st['if_not_exists'], 'index'):
            return Result()
        table = self.get_table(st['table'])
        ix = self.build_index(st, table)
        db.log_schema()
        db.log_table_state(table)
        ix.rootpage = self.new_root()
        table.indexes.append(ix)
        db.indexes[st['name'].lower()] = ix
        db.objects.append(ix)
        return Result()

    def build_index(self, st, table, populate=True):
        scope = Scope(None)
        scope.add(Source(table.name, [c.name for c in table.columns], [c.affinity for c in table.columns],
                         [c.collate for c in table.columns], table=table, has_rowid=True))
        comp = Comp(self.ctx, scope)
        fns = []
        colls = []
        colnames = []
        colidx = []
        for e, coll, desc, text in st['cols']:
            if coll:
                get_collation(coll)
            if e[0] == 'col' and e[1] is None and table.col_index(e[2]) is not None:
                i = table.col_index(e[2])
                fns.append(itemgetter(i))
                colidx.append(i)
                colnames.append('%s.%s' % (table.name, table.columns[i].name))
                colls.append((coll or table.columns[i].collate or '').upper() or None)
            else:
                if e[0] == 'col' and e[1] is None:
                    raise SqlError('no such column: %s' % e[2], 'parse')
                fns.append(comp.comp(e))
                colidx.append(None)
                colnames.append(text)
                colls.append((coll or '').upper() or None)
        pred = comp.comp(st['where']) if st['where'] is not None else None
        ix = Index(st['name'], table, fns, colls, st['unique'], pred=pred, sql=None, colnames=colnames,
                   colidx=None if None in colidx else colidx)
        ix.sql = self.normalize_create(st['sql'], 'INDEX', st['unique'])
        if populate:
            for rid, row in table.rows.items():
                k = ix.key(row)
                if k is None:
                    continue
                if ix.unique and k in ix.map:
                    raise SqlError('UNIQUE constraint failed: %s' % ', '.join(colnames))
                ix.add(row, rid)
        return ix

    def normalize_create(self, raw, kind, unique=False):
        p = Parser(raw)
        toks = p.toks
        i = 1
        while toks[i].kind == 'id' and toks[i].up in ('TEMP', 'TEMPORARY', 'UNIQUE', kind, 'IF', 'NOT', 'EXISTS'):
            i += 1
        return 'CREATE ' + ('UNIQUE ' if unique else '') + kind + ' ' + raw[toks[i].start:]

    def x_create_view(self, st):
        db = self.db
        if not self.check_new_name(st['name'], st['if_not_exists'], 'view'):
            return Result()
        db.log_schema()
        v = View(st['name'], st['select'], st['cols'], st['schema_sql'])
        db.views[v.name.lower()] = v
        db.objects.append(v)
        return Result()

    def x_drop(self, st):
        db = self.db
        what = st['what']
        name = st['name']
        ln = name.lower()
        if what == 'table':
            if ln in db.views:
                raise SqlError('use DROP VIEW to delete view %s' % name, 'parse')
            t = db.tables.get(ln)
            if t is None:
                if st['if_exists']:
                    return Result()
                raise SqlError('no such table: %s' % name, 'parse')
            db.log_schema()
            del db.tables[ln]
            drop = {id(t)}
            for ix in t.indexes:
                db.indexes.pop(ix.name.lower(), None)
                drop.add(id(ix))
            for tn, tr in list(db.triggers.items()):
                if tr.tbl_name.lower() == ln:
                    del db.triggers[tn]
                    drop.add(id(tr))
            db.objects = [o for o in db.objects if id(o) not in drop]
        elif what == 'view':
            if ln in db.tables:
                raise SqlError('use DROP TABLE to delete table %s' % name, 'parse')
            v = db.views.get(ln)
            if v is None:
                if st['if_exists']:
                    return Result()
                raise SqlError('no such view: %s' % name, 'parse')
            db.log_schema()
            del db.views[ln]
            db.objects = [o for o in db.objects if o is not v]
        elif what == 'index':
            ix = db.indexes.get(ln)
            if ix is None:
                if st['if_exists']:
                    return Result()
                for t in db.tables.values():
                    if any(i.name.lower() == ln for i in t.indexes):
                        raise SqlError('index associated with UNIQUE or PRIMARY KEY constraint cannot be dropped',
                                       'parse')
                raise SqlError('no such index: %s' % name, 'parse')
            db.log_schema()
            db.log_table_state(ix.table)
            del db.indexes[ln]
            ix.table.indexes = [i for i in ix.table.indexes if i is not ix]
            db.objects = [o for o in db.objects if o is not ix]
        else:
            tr = db.triggers.get(ln)
            if tr is None:
                if st['if_exists']:
                    return Result()
                raise SqlError('no such trigger: %s' % name, 'parse')
            db.log_schema()
            del db.triggers[ln]
            db.objects = [o for o in db.objects if o is not tr]
        return Result()

    # ------------------------------------------------------------ PRAGMA
    def x_pragma(self, st):
        db = self.db
        name = st['name']
        arg = st['arg']
        if name in ('table_info', 'table_xinfo'):
            t = db.find_relation(str(arg)) if arg is not None else None
            if t is None or isinstance(t, View):
                return Result(['cid', 'name', 'type', 'notnull', 'dflt_value', 'pk'], [])
            rows = []
            for i, c in enumerate(t.columns):
                pk = (t.pk_cols.index(i) + 1) if i in t.pk_cols else 0
                dflt = None
                if c.default is not None:
                    d = c.default
                    dflt = V.to_text(d[1]) if d[0] == 'lit' else None
                    if d[0] == 'lit' and type(d[1]) is str:
                        dflt = "'" + d[1].replace("'", "''") + "'"
                rows.append((i, c.name, c.decl, 1 if c.notnull else 0, dflt, pk))
            return Result(['cid', 'name', 'type', 'notnull', 'dflt_value', 'pk'], rows)
        if name == 'index_list':
            t = db.tables.get(str(arg).lower())
            rows = []
            if t is not None:
                for n, ix in enumerate(reversed(t.indexes)):
                    rows.append((n, ix.name, 1 if ix.unique else 0, 'pk' if False else ('u' if ix.auto else 'c'), 0))
            return Result(['seq', 'name', 'unique', 'origin', 'partial'], rows)
        if name == 'index_info':
            ix = db.indexes.get(str(arg).lower())
            rows = []
            if ix is not None:
                for n, cn in enumerate(ix.colnames):
                    t = ix.table
                    ci = t.col_index(cn.split('.', 1)[-1])
                    rows.append((n, ci if ci is not None else -2, cn.split('.', 1)[-1]))
            return Result(['seqno', 'cid', 'name'], rows)
        if name == 'user_version':
            if arg is None:
                return Result(['user_version'], [(db.user_version,)])
            db.undo.append(('uv', db.user_version))
            db.user_version = int(arg)
            return Result()
        if name in ('integrity_check', 'quick_check'):
            return Result([name], [('ok',)])
        if name == 'encoding':
            return Result(['encoding'], [('UTF-8',)])
        if name == 'schema_version':
            return Result(['schema_version'], [(len(db.objects),)])
        if name == 'database_list':
            return Result(['seq', 'name', 'file'], [(0, 'main', self.path or '')])
        if name == 'foreign_keys':
            return Result(['foreign_keys'], [(0,)]) if arg is None else Result()
        if name == 'journal_mode':
            return Result(['journal_mode'], [('memory' if self.path is None else 'delete',)])
        if name == 'table_list':
            rows = [('main', t.name, 'table', len(t.columns), 0, 0) for t in db.tables.values()]
            return Result(['schema', 'name', 'type', 'ncol', 'wr', 'strict'], rows)
        return Result()
