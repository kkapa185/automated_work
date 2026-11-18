"""Triggers (including INSTEAD OF triggers on views) and DML on views through them."""
from .errors import SqlError, RaiseIgnore
from .catalog import Trigger, View, ROWID_NAMES
from .values import truth, apply_affinity
from .query import Comp, Scope, Source, compile_select, FromPlan


class TriggerMixin:
    active_triggers = ()

    def x_create_trigger(self, st):
        db = self.db
        name = st['name']
        if name.lower() in db.triggers:
            if st['if_not_exists']:
                return None
            raise SqlError('trigger %s already exists' % name, 'parse')
        rel = db.find_relation(st['table'])
        if rel is None or getattr(rel, 'virtual', False):
            raise SqlError('no such table: %s' % st['table'], 'parse')
        if isinstance(rel, View):
            if st['timing'] != 'INSTEAD':
                raise SqlError('cannot create %s trigger on view: %s' % (st['timing'], rel.name), 'parse')
        elif st['timing'] == 'INSTEAD':
            raise SqlError('cannot create INSTEAD OF trigger on table: %s' % rel.name, 'parse')
        db.log_schema()
        tr = Trigger(name, rel.name, st, st['schema_sql'])
        db.triggers[name.lower()] = tr
        db.objects.append(tr)
        return self.empty_result()

    def triggers_for(self, tname, timing, event):
        out = []
        ln = tname.lower()
        for tr in self.db.triggers.values():
            s = tr.stmt
            if tr.tbl_name.lower() == ln and s['timing'] == timing and s['event'] == event:
                out.append(tr)
        return out

    def fire(self, tname, colnames, timing, event, new, old, assigned=None):
        """Run matching triggers. Returns False if a BEFORE/INSTEAD trigger executed RAISE(IGNORE)."""
        if not self.db.triggers:
            return True
        trigs = self.triggers_for(tname, timing, event)
        if not trigs:
            return True
        db = self.db
        ctx = self.ctx
        for tr in trigs:
            if tr.name in self.active_triggers:
                continue
            s = tr.stmt
            if event == 'UPDATE' and s['cols'] and assigned is not None:
                if not ({c.lower() for c in s['cols']} & assigned):
                    continue
            frame = {'new': new, 'old': old, 'cols': [c.lower() for c in colnames]}
            ctx.trigger_stack.append(frame)
            self.active_triggers = tuple(self.active_triggers) + (tr.name,)
            saved = (db.changes,)
            try:
                if s['when'] is not None:
                    w = Comp(ctx, Scope(None)).comp(s['when'])
                    if not truth(w([])):
                        continue
                for body in s['body']:
                    h = getattr(self, 'x_' + body['type'])
                    ctes_len = len(ctx.ctes)
                    h(body)
                    del ctx.ctes[ctes_len:]
            except RaiseIgnore:
                return False
            finally:
                ctx.trigger_stack.pop()
                self.active_triggers = self.active_triggers[:-1]
                db.changes = saved[0]
        return True

    # ------------------------------------------------------------ DML on views via INSTEAD OF triggers
    def view_names(self, view):
        saved = self.ctx.ctes
        self.ctx.ctes = []
        try:
            plan = compile_select(view.select, self.ctx, None)
        finally:
            self.ctx.ctes = saved
        names = list(plan.names)
        if view.cols:
            names = list(view.cols) + names[len(view.cols):]
        return names

    def view_insert(self, st, view):
        names = self.view_names(view)
        if not self.triggers_for(view.name, 'INSTEAD', 'INSERT'):
            raise SqlError('cannot modify %s because it is a view' % view.name, 'parse')
        if st['cols'] is not None:
            pos = []
            for n in st['cols']:
                if n.lower() not in [x.lower() for x in names]:
                    raise SqlError('table %s has no column named %s' % (view.name, n), 'parse')
                pos.append([x.lower() for x in names].index(n.lower()))
        else:
            pos = list(range(len(names)))
        rows = [[]] if st['default_values'] else compile_select(st['source'], self.ctx, None).run()
        count = 0
        for srow in rows:
            new = [None] * len(names) + [None]
            for p, v in zip(pos, srow):
                new[p] = v
            self.fire(view.name, names, 'INSTEAD', 'INSERT', new, None)
            count += 1
        self.db.changes = count
        return self.empty_result()

    def view_scan(self, st, view):
        names = self.view_names(view)
        alias = st['alias'] or view.name
        scope = Scope(None)
        fp = FromPlan(self.ctx, scope, ('table', view.name, st['alias']), st['where'])
        return names, scope, list(fp.iter())

    def view_delete(self, st, view):
        if not self.triggers_for(view.name, 'INSTEAD', 'DELETE'):
            raise SqlError('cannot modify %s because it is a view' % view.name, 'parse')
        names, scope, rows = self.view_scan(st, view)
        for r in rows:
            self.fire(view.name, names, 'INSTEAD', 'DELETE', None, list(r))
        self.db.changes = len(rows)
        return self.empty_result()

    def view_update(self, st, view):
        if not self.triggers_for(view.name, 'INSTEAD', 'UPDATE'):
            raise SqlError('cannot modify %s because it is a view' % view.name, 'parse')
        names, scope, rows = self.view_scan(st, view)
        comp = Comp(self.ctx, scope)
        lnames = [n.lower() for n in names]
        sets = []
        for ns, e in st['sets']:
            if len(ns) != 1:
                raise SqlError('multi-column assignment is not supported on views', 'parse')
            if ns[0].lower() not in lnames:
                raise SqlError('no such column: %s' % ns[0], 'parse')
            sets.append((lnames.index(ns[0].lower()), comp.comp(e)))
        assigned = {names[i].lower() for i, _ in sets}
        for r in rows:
            new = list(r)
            for i, fn in sets:
                new[i] = fn(r)
            self.fire(view.name, names, 'INSTEAD', 'UPDATE', new, list(r), assigned)
        self.db.changes = len(rows)
        return self.empty_result()
