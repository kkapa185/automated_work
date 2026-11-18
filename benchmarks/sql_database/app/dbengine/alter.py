"""ALTER TABLE: implemented by rewriting the stored CREATE statement and rebuilding the table."""
from .errors import SqlError
from .catalog import Trigger, View, Index
from .parser import Parser
from .tokenizer import tokenize
from . import values as V
from .values import apply_affinity
from .query import Comp, Scope


def quote_ident(n):
    return '"' + n.replace('"', '""') + '"'


def replace_tokens(sql, old, new, start_after_paren=False, first_name_only=False):
    """Replace identifier tokens equal (case-insensitively) to old by the quoted new name."""
    toks = tokenize(sql)[:-1]
    out = []
    pos = 0
    seen_paren = not start_after_paren
    lo = old.lower()
    first_done = False
    for i, t in enumerate(toks):
        if t.kind == 'op' and t.val == '(':
            seen_paren = True
        if t.kind in ('id', 'qid') and t.val.lower() == lo and seen_paren:
            if first_name_only:
                if first_done:
                    continue
                first_done = True
            out.append(sql[pos:t.start])
            out.append(quote_ident(new))
            pos = t.end
    out.append(sql[pos:])
    return ''.join(out)


def table_name_token(sql):
    toks = tokenize(sql)
    i = 0
    while i < len(toks) and not (toks[i].kind == 'id' and toks[i].up == 'TABLE'):
        i += 1
    return toks[i + 1]


class AlterMixin:
    def x_alter(self, st):
        db = self.db
        name = st['table']
        t = db.tables.get(name.lower())
        if t is None:
            if name.lower() in db.views:
                raise SqlError('cannot alter a view' if False else 'no such table: %s' % name, 'parse')
            raise SqlError('no such table: %s' % name, 'parse')
        if name.lower().startswith('sqlite_'):
            raise SqlError('table %s may not be altered' % name, 'parse')
        op = st['op']
        if op == 'rename':
            return self.alter_rename(t, st['new'])
        if op == 'rename_column':
            return self.alter_rename_column(t, st['old'], st['new'])
        if op == 'add':
            return self.alter_add(t, st['column'])
        return self.alter_drop(t, st['name'])

    # ------------------------------------------------------------ core rebuild
    def swap_table(self, old, new_sql, rows, index_sqls, trigger_fix=None, view_fix=None):
        db = self.db
        stmt = Parser(new_sql).parse_statement()
        stmt['if_not_exists'] = False
        new = self.build_table(stmt)
        new.sql = stmt['schema_sql']
        new.rootpage = old.rootpage
        for a, b in zip([i for i in old.indexes if i.auto], [i for i in new.indexes if i.auto]):
            b.rootpage = a.rootpage
        new.seq = old.seq
        explicit = [i for i in old.indexes if not i.auto]
        new_explicit = []
        for ix, sql in zip(explicit, index_sqls):
            ist = Parser(sql).parse_statement()
            nix = self.build_index(ist, new, populate=False)
            nix.rootpage = ix.rootpage
            new_explicit.append((ix, nix))
        new.indexes = new.indexes + [n for _, n in new_explicit]
        new.rows = rows
        new.ordered = False
        new.max_rowid = None
        new.scan()
        new.rebuild_indexes()
        for rid, row in new.rows.items():
            pass
        db.log_schema()
        db.tables.pop(old.name.lower(), None)
        db.tables[new.name.lower()] = new
        repl = {id(old): new}
        for ix, nix in new_explicit:
            repl[id(ix)] = nix
            db.indexes[ix.name.lower()] = nix
        for ix in old.indexes:
            if ix.auto:
                pass
        new_triggers = {}
        if trigger_fix:
            for key, tr in list(db.triggers.items()):
                nt = trigger_fix(tr)
                if nt is not None:
                    new_triggers[key] = nt
                    repl[id(tr)] = nt
        new_views = {}
        if view_fix:
            for key, v in list(db.views.items()):
                nv = view_fix(v)
                if nv is not None:
                    new_views[key] = nv
                    repl[id(v)] = nv
        db.triggers.update(new_triggers)
        db.views.update(new_views)
        db.objects = [repl.get(id(o), o) for o in db.objects]
        return self.empty_result()

    def rewrite_trigger(self, tr, sql, tbl_name=None):
        stmt = Parser(sql).parse_statement()
        nt = Trigger(tr.name, tbl_name or tr.tbl_name, stmt, stmt['schema_sql'])
        nt.rootpage = tr.rootpage
        return nt

    def rewrite_view(self, v, sql):
        stmt = Parser(sql).parse_statement()
        nv = View(v.name, stmt['select'], stmt['cols'], stmt['schema_sql'])
        nv.rootpage = v.rootpage
        return nv

    # ------------------------------------------------------------ RENAME TO
    def alter_rename(self, t, newname):
        db = self.db
        if newname.lower() != t.name.lower() and db.name_in_use(newname) is not None:
            raise SqlError('there is already another table or index with this name: %s' % newname, 'parse')
        if newname.lower().startswith('sqlite_'):
            raise SqlError('object name reserved for internal use: %s' % newname, 'parse')
        old = t.name
        tok = table_name_token(t.sql)
        new_sql = t.sql[:tok.start] + quote_ident(newname) + t.sql[tok.end:]
        idx_sqls = []
        for ix in t.indexes:
            if ix.auto:
                continue
            idx_sqls.append(self.rename_index_target(ix.sql, old, newname))

        def tfix(tr):
            if tr.tbl_name.lower() != old.lower():
                return None
            return self.rewrite_trigger(tr, replace_tokens(tr.sql, old, newname), newname)

        def vfix(v):
            if not any(k.kind in ('id', 'qid') and k.val.lower() == old.lower() for k in tokenize(v.sql)):
                return None
            return self.rewrite_view(v, replace_tokens(v.sql, old, newname))
        return self.swap_table(t, new_sql, dict(t.rows), idx_sqls, tfix, vfix)

    @staticmethod
    def rename_index_target(sql, old, new):
        toks = tokenize(sql)
        for i, k in enumerate(toks):
            if k.kind == 'id' and k.up == 'ON' and i + 1 < len(toks):
                n = toks[i + 1]
                return sql[:n.start] + quote_ident(new) + sql[n.end:]
        return sql

    # ------------------------------------------------------------ RENAME COLUMN
    def alter_rename_column(self, t, old, new):
        i = t.col_index(old)
        if i is None:
            raise SqlError('no such column: "%s"' % old, 'parse')
        if new.lower() != old.lower() and t.col_index(new) is not None:
            raise SqlError('duplicate column name: %s' % new, 'parse')
        new_sql = replace_tokens(t.sql, old, new, start_after_paren=True)
        idx_sqls = [replace_tokens(ix.sql, old, new, start_after_paren=True) for ix in t.indexes if not ix.auto]
        tname = t.name

        def tfix(tr):
            if tr.tbl_name.lower() != tname.lower():
                return None
            return self.rewrite_trigger(tr, replace_tokens(tr.sql, old, new))

        def vfix(v):
            if not any(k.kind in ('id', 'qid') and k.val.lower() == tname.lower() for k in tokenize(v.sql)):
                return None
            return self.rewrite_view(v, replace_tokens(v.sql, old, new))
        return self.swap_table(t, new_sql, dict(t.rows), idx_sqls, tfix, vfix)

    # ------------------------------------------------------------ ADD COLUMN
    def alter_add(self, t, cd):
        if t.col_index(cd['name']) is not None:
            raise SqlError('duplicate column name: %s' % cd['name'], 'parse')
        if cd['pk']:
            raise SqlError('Cannot add a PRIMARY KEY column', 'parse')
        if cd['unique']:
            raise SqlError('Cannot add a UNIQUE column', 'parse')
        default = cd['default']
        if cd['notnull'] and (default is None or (default[0] == 'lit' and default[1] is None)):
            raise SqlError('Cannot add a NOT NULL column with default value NULL', 'parse')
        sql = t.sql.rstrip()
        k = sql.rfind(')')
        new_sql = sql[:k] + ', ' + cd['text'] + sql[k:]
        dv = None
        aff = V.type_affinity(cd['type'])
        if default is not None:
            dv = apply_affinity(Comp(self.ctx, Scope(None)).comp(default)([]), aff)
        n = len(t.columns)
        rows = {}
        for rid, row in t.rows.items():
            rows[rid] = row[:n] + [dv] + [rid]
        idx_sqls = [ix.sql for ix in t.indexes if not ix.auto]
        return self.swap_table(t, new_sql, rows, idx_sqls)

    # ------------------------------------------------------------ DROP COLUMN
    def alter_drop(self, t, name):
        i = t.col_index(name)
        if i is None:
            raise SqlError('no such column: "%s"' % name, 'parse')
        if len(t.columns) == 1:
            raise SqlError('cannot drop column "%s": no other columns exist' % name, 'parse')
        if i in t.pk_cols:
            raise SqlError('cannot drop PRIMARY KEY column: "%s"' % name, 'parse')
        for ix in t.indexes:
            if ix.colidx is None or i in ix.colidx:
                if ix.auto:
                    raise SqlError('cannot drop UNIQUE column: "%s"' % name, 'parse')
                raise SqlError('error in index %s after drop column: no such column: %s' % (ix.name, name), 'parse')
        # remove the column definition text from the CREATE statement
        toks = tokenize(t.sql)[:-1]
        depth = 0
        defs = []      # (start_index_of_def_tokens, end_exclusive)
        cur = None
        first_paren = None
        for k, tk in enumerate(toks):
            if tk.kind == 'op' and tk.val == '(':
                depth += 1
                if depth == 1:
                    first_paren = k
                    cur = k + 1
                continue
            if tk.kind == 'op' and tk.val == ')':
                depth -= 1
                if depth == 0:
                    defs.append((cur, k))
                    break
                continue
            if tk.kind == 'op' and tk.val == ',' and depth == 1:
                defs.append((cur, k))
                cur = k + 1
        target = None
        for si, (a, b) in enumerate(defs):
            if toks[a].val.lower() == name.lower() and toks[a].kind in ('id', 'qid'):
                target = si
                break
        if target is None:
            raise SqlError('cannot drop column "%s"' % name, 'parse')
        a, b = defs[target]
        if target + 1 < len(defs):
            cut_from = toks[a].start
            cut_to = toks[defs[target + 1][0]].start
        else:
            cut_from = toks[a - 1].start if target > 0 else toks[a].start
            cut_to = toks[b].start
            if target == 0:
                cut_from = toks[a].start
        new_sql = t.sql[:cut_from] + t.sql[cut_to:]
        rows = {}
        for rid, row in t.rows.items():
            rows[rid] = row[:i] + row[i + 1:]
        idx_sqls = [ix.sql for ix in t.indexes if not ix.auto]
        # index definitions referring to later columns are by name, so they stay valid
        return self.swap_table(t, new_sql, rows, idx_sqls)
