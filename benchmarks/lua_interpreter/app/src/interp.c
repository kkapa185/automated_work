/* Tree-walking evaluator, call machinery, error handling. */
#include "lua.h"
#include <stdarg.h>
#include <alloca.h>

enum { EX_OK = 0, EX_BREAK, EX_RETURN, EX_GOTO, EX_TAIL };
static Label *goto_target;
Node for_iter_marker;

static int eval_multi(State *L, Frame *f, Node *n, Value **out);
static Value eval(State *L, Frame *f, Node *n);
static int exec_block(State *L, Frame *f, Block *b);

/* ---------- errors ---------- */
static void fatal_unprotected(State *L, Value v) {
  (void)L;
  Value s = v.t == T_STR ? v : tostring_basic(v);
  fprintf(stderr, "lua: unprotected error: %s\n", strof(s)->data);
  exit(1);
}
void lua_throw(State *L, Value v) {
  ErrJmp *ej = L->ej;
  if (!ej) fatal_unprotected(L, v);
  if (!isnil(ej->handler) && !ej->inhandler) {
    ErrJmp hej; memset(&hej, 0, sizeof hej);
    hej.prev = ej; hej.handler = NILV; hej.ci = L->ci; hej.depth = L->depth; hej.ntbc = L->ntbc; hej.inhandler = 1;
    ej->inhandler = 1;
    int oldmax = L->maxdepth; L->maxdepth += 3000;
    L->ej = &hej;
    if (setjmp(hej.jb) == 0) {
      Value args[1] = {v};
      Value h = ej->handler;
      int r = call_value(L, h, args, 1);
      v = r > 0 ? L->ret[0] : NILV;
    } else {
      v = hej.err; L->ci = hej.ci; L->depth = hej.depth;
    }
    L->ej = ej; L->maxdepth = oldmax;
    ej->inhandler = 0;
  }
  ej->err = v;
  longjmp(ej->jb, 1);
}
static void short_src_of(CallInfo *ci, char *out, size_t n) {
  snprintf(out, n, "%s", ci->cl->p->chunk->short_src);
}
Str *where_str(State *L, int level) {
  CallInfo *ci = L->ci;
  while (level-- > 0 && ci) ci = ci->prev;
  if (ci && ci->cl) { char s[80]; short_src_of(ci, s, sizeof s); return str_fmt("%s:%d: ", s, ci->line); }
  return str_newz("");
}
void lerror(State *L, const char *fmt, ...) {
  char buf[1024]; va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap);
  CallInfo *ci = L->ci;
  if (ci && ci->cf) ci = ci->prev;
  Str *msg;
  if (ci && ci->cl) { char s[80]; short_src_of(ci, s, sizeof s); msg = str_fmt("%s:%d: %s", s, ci->line, buf); }
  else msg = str_newz(buf);
  lua_throw(L, mkstr(msg));
}
void ret_need(State *L, int n) {
  if (n <= L->retcap) return;
  int nc = L->retcap * 2; if (nc < n) nc = n + 16;
  Value *nr = realloc(L->ret, (size_t)nc * sizeof(Value));
  if (!nr) { fputs("lua: not enough memory\n", stderr); exit(1); }
  for (int i = L->retcap; i < nc; i++) nr[i] = NILV;
  gc_account((long)(nc - L->retcap) * (long)sizeof(Value));
  L->ret = nr; L->retcap = nc;
}
static void tail_need(State *L, int n) {
  if (n <= L->tailcap) return;
  int nc = L->tailcap * 2; if (nc < n) nc = n + 16;
  Value *nr = realloc(L->tail, (size_t)nc * sizeof(Value));
  if (!nr) { fputs("lua: not enough memory\n", stderr); exit(1); }
  for (int i = L->tailcap; i < nc; i++) nr[i] = NILV;
  L->tail = nr; L->tailcap = nc;
}

/* ---------- to-be-closed variables ---------- */
static void tbc_push(State *L, Value v) {
  if (L->ntbc == L->tbccap) {
    L->tbccap = L->tbccap ? L->tbccap * 2 : 8;
    L->tbc = realloc(L->tbc, (size_t)L->tbccap * sizeof(Value));
  }
  L->tbc[L->ntbc++] = v;
}
void tbc_close_to(State *L, int level, Value err, int haserr) {
  while (L->ntbc > level) {
    Value v = L->tbc[--L->ntbc];
    Value tm = get_tm(v, TM_CLOSE);
    if (isnil(tm)) lerror(L, "metamethod 'close' is not callable");
    Value args[2] = {v, err};
    call_value(L, tm, args, haserr ? 2 : 1);
  }
}
Value tbc_unwind(State *L, int level, Value err) {
  while (L->ntbc > level) {
    ErrJmp ej; memset(&ej, 0, sizeof ej);
    ej.prev = L->ej; ej.handler = NILV; ej.ci = L->ci; ej.depth = L->depth; ej.ntbc = L->ntbc;
    L->ej = &ej;
    if (setjmp(ej.jb) == 0) { tbc_close_to(L, level, err, 1); L->ej = ej.prev; }
    else { L->ej = ej.prev; L->ci = ej.ci; L->depth = ej.depth; err = ej.err; }
  }
  return err;
}

/* ---------- node descriptions for error messages ---------- */
static const char *varinfo(Node *e, char *buf, size_t sz) {
  buf[0] = 0;
  if (!e) return buf;
  switch (e->k) {
    case E_LOCAL: case E_BOXED: snprintf(buf, sz, " (local '%s')", e->name->data); break;
    case E_UPVAL: snprintf(buf, sz, " (upvalue '%s')", e->name->data); break;
    case E_FIELD: snprintf(buf, sz, e->flag & 1 ? " (global '%s')" : " (field '%s')", e->name->data); break;
    case E_METH: snprintf(buf, sz, " (method '%s')", e->name->data); break;
    case E_STR: snprintf(buf, sz, " (constant '%s')", e->u.s->data); break;
    case E_INDEX: if (e->b->k == E_STR) snprintf(buf, sz, " (field '%s')", e->b->u.s->data); break;
    default: break;
  }
  return buf;
}

/* ---------- calls ---------- */
static void __attribute__((noinline)) stack_overflow(State *L) {
  lerror(L, "stack overflow");
}
size_t stack_avail(State *L) {
  char probe;
  return &probe > L->stack_lo ? (size_t)(&probe - L->stack_lo) : 0;
}
static inline void need_stack(State *L, size_t bytes) {
  if (stack_avail(L) < bytes + 65536) stack_overflow(L);
}
static inline int call_c(State *L, CFn *c, Value *args, int nargs) {
  CallInfo ci;
  if (L->depth >= L->maxdepth || (char *)&ci < L->stack_lo) stack_overflow(L);
  ci.prev = L->ci; ci.cl = NULL; ci.cf = c; ci.line = 0; ci.callnode = L->callnode; ci.istail = 0;
  L->callnode = NULL;
  L->depth++; L->ci = &ci;
  int r = c->fn(L, args, nargs);
  L->ci = ci.prev; L->depth--;
  return r;
}

static int __attribute__((noinline)) run_closure(State *L, Closure *cl, Value *args, int nargs) {
  Proto *p = cl->p;
  Value *slots = alloca((size_t)p->nslots * sizeof(Value));
  memset(slots, 0, (size_t)p->nslots * sizeof(Value));
  Frame f; f.slots = slots; f.cl = cl; f.varargs = NULL; f.nvarargs = 0; f.ci = L->ci;
  int np = p->nparams;
  for (int i = 0; i < np; i++) {
    Value v = i < nargs ? args[i] : NILV;
    slots[i] = p->params[i]->captured ? mkobj(T_BOX, box_new(v)) : v;
  }
  if (p->is_vararg && nargs > np) {
    f.nvarargs = nargs - np;
    need_stack(L, (size_t)f.nvarargs * sizeof(Value));
    f.varargs = alloca((size_t)f.nvarargs * sizeof(Value));
    memcpy(f.varargs, args + np, (size_t)f.nvarargs * sizeof(Value));
  }
  int r = exec_block(L, &f, p->body);
  if (r == EX_TAIL) return -1;
  if (r != EX_RETURN) L->nret = 0;
  return L->nret;
}

/* Zero the stack area below the caller so that frames built there do not contain stale words from earlier,
 * deeper activity (they would be scanned conservatively and could keep dead objects alive). */
static void __attribute__((noinline)) scrub_stack(void) {
  char buf[3072];
  memset(buf, 0, sizeof buf);
  __asm__ volatile("" : : "r"(buf) : "memory");
}

int call_lua(State *L, Closure *cl, Value *args, int nargs) {
  CallInfo ci;
  if (L->depth >= L->maxdepth || (char *)&ci < L->stack_lo) stack_overflow(L);
  ci.prev = L->ci; ci.cl = cl; ci.cf = NULL; ci.line = cl->p->line; ci.callnode = L->callnode; ci.istail = 0;
  L->callnode = NULL;
  L->depth++; L->ci = &ci;
  gc_check(L);
  if (L->depth <= 12) scrub_stack();
  int r;
  for (;;) {
    r = run_closure(L, cl, args, nargs);
    if (r >= 0) break;
    Value fn = L->tailfn; args = L->tail; nargs = L->ntail;
    ci.istail = 1; ci.callnode = NULL;
    cl = fn.u.p; ci.cl = cl; ci.line = cl->p->line;
  }
  L->ci = ci.prev; L->depth--;
  return r;
}

int call_value(State *L, Value fn, Value *args, int nargs) {
  if (fn.t == T_LCL) return call_lua(L, fn.u.p, args, nargs);
  if (fn.t == T_CFN) return call_c(L, fn.u.p, args, nargs);
  Value tm = get_tm(fn, TM_CALL);
  if (isnil(tm)) lerror(L, "attempt to call a %s value", objtypename(fn));
  char probe;
  if (L->depth >= L->maxdepth || &probe - ((size_t)nargs + 8) * sizeof(Value) < L->stack_lo) stack_overflow(L);
  Value *na = alloca(((size_t)nargs + 1) * sizeof(Value));
  na[0] = fn; memcpy(na + 1, args, (size_t)nargs * sizeof(Value));
  L->depth++;
  int r = call_value(L, tm, na, nargs + 1);
  L->depth--;
  return r;
}
int protected_call(State *L, Value fn, Value *args, int n, Value *err) {
  ErrJmp ej; memset(&ej, 0, sizeof ej);
  ej.prev = L->ej; ej.handler = NILV; ej.ci = L->ci; ej.depth = L->depth; ej.ntbc = L->ntbc;
  L->ej = &ej;
  if (setjmp(ej.jb) == 0) { int r = call_value(L, fn, args, n); L->ej = ej.prev; return r; }
  L->ej = ej.prev; L->ci = ej.ci; L->depth = ej.depth;
  *err = tbc_unwind(L, ej.ntbc, ej.err);
  return -1;
}
Value call1(State *L, Value fn, Value *args, int n) {
  int r = call_value(L, fn, args, n);
  return r > 0 ? L->ret[0] : NILV;
}

/* ---------- slow paths with error info ---------- */
static Value __attribute__((noinline)) index_slow(State *L, Frame *f, Node *n, Value o, Value k) {
  f->ci->line = n->line;
  int ok; Value r = index_val(L, o, k, &ok);
  if (!ok) {
    char vb[160];
    const char *vi = r.t == o.t ? varinfo(n->a, vb, sizeof vb) : "";
    if (n->k == E_FIELD && n->a->k != E_FIELD && n->a->k != E_LOCAL && n->a->k != E_BOXED && n->a->k != E_UPVAL) vi = "";
    lerror(L, "attempt to index a %s value%s", objtypename(r), vi);
  }
  return r;
}
static void __attribute__((noinline)) setindex_slow(State *L, Frame *f, Node *n, Value o, Value k, Value v) {
  f->ci->line = n->line;
  Value bad;
  if (!setindex_val(L, o, k, v, &bad)) {
    char vb[160];
    const char *vi = bad.t == o.t ? varinfo(n->a, vb, sizeof vb) : "";
    lerror(L, "attempt to index a %s value%s", objtypename(bad), vi);
  }
}
static Value __attribute__((noinline)) arith_slow(State *L, Frame *f, Node *n, Value a, Value b) {
  f->ci->line = n->line;
  Value r;
  int s = arith_try(L, n->op, a, b, &r);
  if (s == 1) return r;
  if (s == -1) lerror(L, "number has no integer representation");
  char vb[160];
  Value bad = L->badop == 1 ? a : b;
  const char *vi = varinfo(L->badop == 1 ? n->a : n->b, vb, sizeof vb);
  lerror(L, "attempt to perform %s on a %s value%s", n->op >= OP_BAND ? "bitwise operation" : "arithmetic", objtypename(bad), vi);
}

static int __attribute__((noinline)) compare_slow(State *L, Frame *f, Node *n, Value a, Value b) {
  f->ci->line = n->line;
  switch (n->op) {
    case OP_EQ: return val_equal(L, a, b);
    case OP_NE: return !val_equal(L, a, b);
    case OP_LT: return val_lt(L, a, b);
    case OP_LE: return val_le(L, a, b);
    case OP_GT: return val_lt(L, b, a);
    default: return val_le(L, b, a);
  }
}
static inline int compare(State *L, Frame *f, Node *n) {
  Value a = eval(L, f, n->a), b = eval(L, f, n->b);
  switch (n->op) {
    case OP_EQ: if (a.t == b.t && a.t != T_TABLE && a.t != T_UDATA) return raw_equal(a, b); break;
    case OP_NE: if (a.t == b.t && a.t != T_TABLE && a.t != T_UDATA) return !raw_equal(a, b); break;
    case OP_LT: if (a.t == T_INT && b.t == T_INT) return a.u.i < b.u.i; if (a.t == T_FLT && b.t == T_FLT) return a.u.n < b.u.n; break;
    case OP_LE: if (a.t == T_INT && b.t == T_INT) return a.u.i <= b.u.i; if (a.t == T_FLT && b.t == T_FLT) return a.u.n <= b.u.n; break;
    case OP_GT: if (a.t == T_INT && b.t == T_INT) return a.u.i > b.u.i; if (a.t == T_FLT && b.t == T_FLT) return a.u.n > b.u.n; break;
    default: if (a.t == T_INT && b.t == T_INT) return a.u.i >= b.u.i; if (a.t == T_FLT && b.t == T_FLT) return a.u.n >= b.u.n; break;
  }
  return compare_slow(L, f, n, a, b);
}
static int cond(State *L, Frame *f, Node *n) {
  switch (n->k) {
    case E_TRUE: return 1;
    case E_FALSE: case E_NIL: return 0;
    case E_NOT: return !cond(L, f, n->a);
    case E_AND: return cond(L, f, n->a) && cond(L, f, n->b);
    case E_OR: return cond(L, f, n->a) || cond(L, f, n->b);
    case E_BIN: if (n->op >= OP_EQ) return compare(L, f, n); /* fallthrough */
    default: return truthy(eval(L, f, n));
  }
}

static void __attribute__((noinline)) call_error(State *L, Frame *f, Node *n, Value fn) {
  char vb[160];
  f->ci->line = n->line;
  const char *vi = n->k == E_METH ? varinfo(n, vb, sizeof vb) : varinfo(n->a, vb, sizeof vb);
  lerror(L, "attempt to call a %s value%s", objtypename(fn), vi);
}

static inline int is_multi(Node *n) { return n->k == E_CALL || n->k == E_METH || n->k == E_VARARG; }

static int __attribute__((noinline)) do_call(State *L, Frame *f, Node *n, int tail) {
  Value fn; Value *args; int nargs;
  Node **al = n->list; int na = n->n;
  int self = 0; Value obj = NILV;
  if (n->k == E_METH) {
    obj = eval(L, f, n->a);
    self = 1;
    if (obj.t == T_TABLE) {
      Table *t = tabof(obj);
      fn = tab_getstr(t, n->name);
      if (isnil(fn) && t->meta) fn = index_slow(L, f, n, obj, mkstr(n->name));
    } else fn = index_slow(L, f, n, obj, mkstr(n->name));
  } else fn = eval(L, f, n->a);
  int multi = na > 0 && is_multi(al[na - 1]);
  if (!multi) {
    nargs = self + na;
    need_stack(L, ((size_t)nargs + 1) * sizeof(Value));
    args = alloca(((size_t)nargs + 1) * sizeof(Value));
    args[nargs] = NILV;
    if (self) args[0] = obj;
    for (int i = 0; i < na; i++) args[self + i] = eval(L, f, al[i]);
  } else {
    int nf = na - 1;
    need_stack(L, ((size_t)self + (size_t)nf + 1) * sizeof(Value));
    Value *t = alloca(((size_t)self + (size_t)nf + 1) * sizeof(Value));
    if (self) t[0] = obj;
    for (int i = 0; i < nf; i++) t[self + i] = eval(L, f, al[i]);
    Value *mv; int m = eval_multi(L, f, al[na - 1], &mv);
    nargs = self + nf + m;
    need_stack(L, ((size_t)nargs + 1) * sizeof(Value));
    args = alloca(((size_t)nargs + 1) * sizeof(Value));
    memcpy(args, t, ((size_t)self + (size_t)nf) * sizeof(Value));
    memcpy(args + self + nf, mv, (size_t)m * sizeof(Value));
  }
  f->ci->line = n->line;
  if (fn.t != T_LCL && fn.t != T_CFN && isnil(get_tm(fn, TM_CALL))) call_error(L, f, n, fn);
  L->callnode = n;
  if (tail && fn.t == T_LCL) {
    tail_need(L, nargs);
    memcpy(L->tail, args, (size_t)nargs * sizeof(Value));
    L->ntail = nargs; L->tailfn = fn;
    return -1;
  }
  return call_value(L, fn, args, nargs);
}

static int eval_multi(State *L, Frame *f, Node *n, Value **out) {
  switch (n->k) {
    case E_VARARG: *out = f->varargs; return f->nvarargs;
    default: { int r = do_call(L, f, n, 0); *out = L->ret; return r; }
  }
}

static inline Value mkclosure(State *L, Frame *f, Proto *p) {
  Closure *c = closure_new(p, p->nup);
  for (int i = 0; i < p->nup; i++) {
    UpDesc *d = &p->up[i];
    c->upv[i] = d->fromlocal ? (Box *)f->slots[d->idx].u.p : f->cl->upv[d->idx];
  }
  (void)L;
  return mkobj(T_LCL, c);
}

#define ARITH_CASE(OPC, IEXPR, FEXPR) \
  case OPC: \
    if (a.t == T_INT && b.t == T_INT) { lint x = a.u.i, y = b.u.i; (void)x; (void)y; return IEXPR; } \
    if (a.t == T_FLT && b.t == T_FLT) { lnum x = a.u.n, y = b.u.n; (void)x; (void)y; return FEXPR; } \
    break;

static Value __attribute__((noinline)) eval_concat(State *L, Frame *f, Node *n) {
  int c = n->n;
  need_stack(L, (size_t)c * sizeof(Value));
  Value *v = alloca((size_t)c * sizeof(Value));
  int all = 1;
  for (int i = 0; i < c; i++) { v[i] = eval(L, f, n->list[i]); if (!(v[i].t == T_STR || isnum(v[i]))) all = 0; }
  f->ci->line = n->line;
  if (all) return concat_vals(L, v, c);
  Value acc = v[c - 1];
  for (int i = c - 2; i >= 0; i--) {
    Value l = v[i], pair[2] = {l, acc};
    int ls = l.t == T_STR || isnum(l), as = acc.t == T_STR || isnum(acc);
    if (ls && as) acc = concat_vals(L, pair, 2);
    else {
      Value r;
      if (!concat_try(L, l, acc, &r)) {
        char vb[160];
        Node *bn = ls ? (i == c - 2 ? n->list[c - 1] : NULL) : n->list[i];
        Value bad = ls ? acc : l;
        lerror(L, "attempt to concatenate a %s value%s", objtypename(bad), varinfo(bn, vb, sizeof vb));
      }
      acc = r;
    }
  }
  return acc;
}

static Value __attribute__((noinline)) eval_table(State *L, Frame *f, Node *n) {
  int npos = 0, nkey = 0;
  for (int i = 0; i < n->n; i++) { if (n->list[i]->k == IT_POS) npos++; else nkey++; }
  Table *t = tab_new(npos, nkey);
  lint idx = 1;
  for (int i = 0; i < n->n; i++) {
    Node *it = n->list[i];
    if (it->k == IT_POS) {
      if (i == n->n - 1 && is_multi(it->a)) {
        Value *mv; int m = eval_multi(L, f, it->a, &mv);
        if (m > 0) {
          tab_reserve_arr(t, (uint32_t)(idx - 1 + m));
          for (int j = 0; j < m; j++) tab_ctor_set(L, t, idx++, mv[j]);
        }
      } else { Value v = eval(L, f, it->a); tab_ctor_set(L, t, idx++, v); }
    } else {
      Value k = eval(L, f, it->a), v = eval(L, f, it->b);
      f->ci->line = it->line;
      if (isnil(k)) lerror(L, "table index is nil");
      tab_set(L, t, k, v);
    }
  }
  return mktab(t);
}

static Value eval(State *L, Frame *f, Node *n) {
  char probe;
  if (&probe < L->stack_lo) stack_overflow(L);
  switch (n->k) {
    case E_NIL: return NILV;
    case E_TRUE: return mkbool(1);
    case E_FALSE: return mkbool(0);
    case E_INT: return mkint(n->u.i);
    case E_FLT: return mkflt(n->u.n);
    case E_STR: return mkstr(n->u.s);
    case E_VARARG: return f->nvarargs > 0 ? f->varargs[0] : NILV;
    case E_LOCAL: return f->slots[n->slot];
    case E_BOXED: return ((Box *)f->slots[n->slot].u.p)->v;
    case E_UPVAL: return f->cl->upv[n->slot]->v;
    case E_FIELD: {
      Value o = eval(L, f, n->a);
      if (o.t == T_TABLE) {
        Table *t = tabof(o);
        Value v = tab_getstr(t, n->name);
        if (!isnil(v) || !t->meta) return v;
      }
      return index_slow(L, f, n, o, mkstr(n->name));
    }
    case E_INDEX: {
      Value o = eval(L, f, n->a), k = eval(L, f, n->b);
      if (o.t == T_TABLE) {
        Table *t = tabof(o);
        Value v = k.t == T_INT ? tab_getint(t, k.u.i) : tab_get(t, k);
        if (!isnil(v) || !t->meta) return v;
      }
      return index_slow(L, f, n, o, k);
    }
    case E_CALL: case E_METH: { int r = do_call(L, f, n, 0); return r > 0 ? L->ret[0] : NILV; }
    case E_FUNC: return mkclosure(L, f, n->u.p);
    case E_PAREN: return eval(L, f, n->a);
    case E_AND: { Value a = eval(L, f, n->a); if (!truthy(a)) return a; return eval(L, f, n->b); }
    case E_OR: { Value a = eval(L, f, n->a); if (truthy(a)) return a; return eval(L, f, n->b); }
    case E_NOT: return mkbool(!cond(L, f, n->a));
    case E_BIN: {
      if (n->op >= OP_EQ) return mkbool(compare(L, f, n));
      Value a = eval(L, f, n->a), b = eval(L, f, n->b);
      switch (n->op) {
        ARITH_CASE(OP_ADD, mkint((lint)((luint)x + (luint)y)), mkflt(x + y))
        ARITH_CASE(OP_SUB, mkint((lint)((luint)x - (luint)y)), mkflt(x - y))
        ARITH_CASE(OP_MUL, mkint((lint)((luint)x * (luint)y)), mkflt(x * y))
        case OP_DIV:
          if (a.t == T_INT && b.t == T_INT) return mkflt((lnum)a.u.i / (lnum)b.u.i);
          if (a.t == T_FLT && b.t == T_FLT) return mkflt(a.u.n / b.u.n);
          break;
        case OP_MOD:
          if (a.t == T_INT && b.t == T_INT && b.u.i > 0) { lint m = a.u.i % b.u.i; if (m < 0) m += b.u.i; return mkint(m); }
          break;
        case OP_IDIV:
          if (a.t == T_INT && b.t == T_INT && b.u.i > 0) { lint q = a.u.i / b.u.i; if ((a.u.i % b.u.i) < 0) q--; return mkint(q); }
          break;
        case OP_BAND: if (a.t == T_INT && b.t == T_INT) return mkint(a.u.i & b.u.i); break;
        case OP_BOR: if (a.t == T_INT && b.t == T_INT) return mkint(a.u.i | b.u.i); break;
        case OP_BXOR: if (a.t == T_INT && b.t == T_INT) return mkint(a.u.i ^ b.u.i); break;
        default: break;
      }
      return arith_slow(L, f, n, a, b);
    }
    case E_NEG: {
      Value a = eval(L, f, n->a);
      if (a.t == T_INT) return mkint((lint)((luint)0 - (luint)a.u.i));
      if (a.t == T_FLT) return mkflt(-a.u.n);
      f->ci->line = n->line;
      Value x;
      if (a.t == T_STR && tonumber_v(a, &x)) return x.t == T_INT ? mkint((lint)((luint)0 - (luint)x.u.i)) : mkflt(-x.u.n);
      Value tm = get_tm(a, TM_UNM);
      if (!isnil(tm)) { Value args[2] = {a, a}; return call1(L, tm, args, 2); }
      char vb[160];
      lerror(L, "attempt to perform arithmetic on a %s value%s", objtypename(a), varinfo(n->a, vb, sizeof vb));
    }
    case E_BNOT: {
      Value a = eval(L, f, n->a);
      if (a.t == T_INT) return mkint(~a.u.i);
      f->ci->line = n->line;
      Value x; lint i;
      if (tonumber_v(a, &x)) {
        if (tointeger_num(x, &i)) return mkint(~i);
        lerror(L, "number has no integer representation");
      }
      Value tm = get_tm(a, TM_BNOT);
      if (!isnil(tm)) { Value args[2] = {a, a}; return call1(L, tm, args, 2); }
      char vb[160];
      lerror(L, "attempt to perform bitwise operation on a %s value%s", objtypename(a), varinfo(n->a, vb, sizeof vb));
    }
    case E_LEN: {
      Value a = eval(L, f, n->a);
      if (a.t == T_STR) return mkint((lint)strof(a)->len);
      if (a.t == T_TABLE && !tabof(a)->meta) return mkint(tab_len(tabof(a)));
      f->ci->line = n->line;
      int ok; Value r = len_val(L, a, &ok);
      if (!ok) { char vb[160]; lerror(L, "attempt to get length of a %s value%s", objtypename(a), varinfo(n->a, vb, sizeof vb)); }
      return r;
    }
    case E_CONCAT: return eval_concat(L, f, n);
    case E_TABLE: return eval_table(L, f, n);
    default: lerror(L, "internal error: bad expression node %d", n->k);
  }
}

/* ---------- statements ---------- */
static inline void set_local(Frame *f, VarInfo *vi, Value v) {
  f->slots[vi->slot] = vi->captured ? mkobj(T_BOX, box_new(v)) : v;
}
static void assign_to(State *L, Frame *f, Node *t, Value o, Value k, Value v) {
  switch (t->k) {
    case E_LOCAL: f->slots[t->slot] = v; break;
    case E_BOXED: ((Box *)f->slots[t->slot].u.p)->v = v; break;
    case E_UPVAL: f->cl->upv[t->slot]->v = v; break;
    case E_FIELD:
      if (o.t == T_TABLE && !tabof(o)->meta) tab_setstr(L, tabof(o), t->name, v);
      else setindex_slow(L, f, t, o, mkstr(t->name), v);
      break;
    default: /* E_INDEX */
      if (o.t == T_TABLE && !tabof(o)->meta) { f->ci->line = t->line; tab_set(L, tabof(o), k, v); }
      else setindex_slow(L, f, t, o, k, v);
  }
}

/* evaluate expression list adjusted to `want` values into out[] */
static void eval_adjust(State *L, Frame *f, Node **list, int n, Value *out, int want) {
  int i;
  for (i = 0; i < n; i++) {
    Node *e = list[i];
    if (i == n - 1 && is_multi(e)) {
      Value *mv; int m = eval_multi(L, f, e, &mv);
      for (int j = 0; i + j < want; j++) out[i + j] = j < m ? mv[j] : NILV;
      return;
    }
    Value v = eval(L, f, e);
    if (i < want) out[i] = v;
  }
  for (; i < want; i++) out[i] = NILV;
}

static void check_close_value(State *L, Frame *f, VarInfo *vi, Value v, int line) {
  if (!truthy(v)) return;
  f->ci->line = line;
  if (isnil(get_tm(v, TM_CLOSE))) lerror(L, "variable '%s' got a non-closable value", vi->name->data);
  tbc_push(L, v);
}

static int forlimit(State *L, Value lim, lint init, lint step, lint *out) { /* returns 1 to skip loop */
  lint l;
  if (lim.t == T_INT) l = lim.u.i;
  else if (lim.t == T_FLT) {
    lnum d = lim.u.n;
    if (d != d) return 1;
    lnum fl = step < 0 ? ceil(d) : floor(d);
    if (fl >= -9223372036854775808.0 && fl < 9223372036854775808.0) l = (lint)fl;
    else if (d > 0) { if (step < 0) return 1; l = INT64_MAX; }
    else { if (step > 0) return 1; l = INT64_MIN; }
  } else lerror(L, "'for' limit must be a number");
  *out = l;
  return step > 0 ? init > l : init < l;
}

static int __attribute__((noinline)) exec_fornum(State *L, Frame *f, Node *s) {
  f->ci->line = s->line;
  Value v0 = eval(L, f, s->a), v1 = eval(L, f, s->b), v2 = s->c ? eval(L, f, s->c) : mkint(1);
  f->ci->line = s->line;
  VarInfo *vi = s->u.vi; Value *slot = &f->slots[vi->slot]; int cap = vi->captured;
  if (v0.t == T_INT && v2.t == T_INT) {
    lint start = v0.u.i, step = v2.u.i, limit;
    if (step == 0) lerror(L, "'for' step is zero");
    if (forlimit(L, v1, start, step, &limit)) return EX_OK;
    luint count = step > 0 ? ((luint)limit - (luint)start) / (luint)step
                           : ((luint)start - (luint)limit) / ((luint)(-(step + 1)) + 1u);
    lint i = start;
    for (;;) {
      *slot = cap ? mkobj(T_BOX, box_new(mkint(i))) : mkint(i);
      int r = exec_block(L, f, s->blk);
      if (r) { if (r == EX_BREAK) break; return r; }
      if (count-- == 0) break;
      i = (lint)((luint)i + (luint)step);
      gc_check(L);
    }
    return EX_OK;
  }
  if (!isnum(v1)) lerror(L, "'for' limit must be a number");
  if (!isnum(v2)) lerror(L, "'for' step must be a number");
  if (!isnum(v0)) lerror(L, "'for' initial value must be a number");
  lnum a = v0.t == T_INT ? (lnum)v0.u.i : v0.u.n, lim = v1.t == T_INT ? (lnum)v1.u.i : v1.u.n,
       st = v2.t == T_INT ? (lnum)v2.u.i : v2.u.n;
  if (st == 0) lerror(L, "'for' step is zero");
  for (; st > 0 ? a <= lim : lim <= a; a += st) {
    *slot = cap ? mkobj(T_BOX, box_new(mkflt(a))) : mkflt(a);
    int r = exec_block(L, f, s->blk);
    if (r) { if (r == EX_BREAK) break; return r; }
    gc_check(L);
  }
  return EX_OK;
}

static int __attribute__((noinline)) exec_forin(State *L, Frame *f, Node *s) {
  Value fv[4];
  eval_adjust(L, f, s->list, s->n, fv, 4);
  Value fn = fv[0], st = fv[1], ctl = fv[2], cv = fv[3];
  VarInfo **vars = s->u.vars; int nv = s->slot;
  int base = L->ntbc, pushed = 0;
  int r = EX_OK;
  if (!isnil(cv)) {
    f->ci->line = s->line;
    if (isnil(get_tm(cv, TM_CLOSE))) lerror(L, "variable '(for state)' got a non-closable value");
    tbc_push(L, cv); pushed = 1;
  }
  if (fn.t == T_CFN && (CFn *)fn.u.p == G.next_fn && st.t == T_TABLE && isnil(ctl)) {
    Table *t = tabof(st); size_t cur = 0; Value k, v;
    while (tab_iter(t, &cur, &k, &v)) {
      set_local(f, vars[0], k);
      if (nv > 1) { set_local(f, vars[1], v); for (int i = 2; i < nv; i++) set_local(f, vars[i], NILV); }
      r = exec_block(L, f, s->blk);
      if (r) { if (r == EX_BREAK) r = EX_OK; break; }
      gc_check(L);
    }
  } else if (fn.t == T_CFN && (CFn *)fn.u.p == G.ipairs_iter && st.t == T_TABLE && !tabof(st)->meta && ctl.t == T_INT) {
    Table *t = tabof(st); lint i = ctl.u.i;
    for (;;) {
      i++;
      Value v = tab_getint(t, i);
      if (isnil(v)) break;
      set_local(f, vars[0], mkint(i));
      if (nv > 1) { set_local(f, vars[1], v); for (int j = 2; j < nv; j++) set_local(f, vars[j], NILV); }
      r = exec_block(L, f, s->blk);
      if (r) { if (r == EX_BREAK) r = EX_OK; break; }
      gc_check(L);
    }
  } else {
    for (;;) {
      Value args[2] = {st, ctl};
      f->ci->line = s->line;
      if (fn.t != T_LCL && fn.t != T_CFN && isnil(get_tm(fn, TM_CALL)))
        lerror(L, "attempt to call a %s value (for iterator 'for iterator')", objtypename(fn));
      L->callnode = &for_iter_marker;
      int nr = call_value(L, fn, args, 2);
      Value first = nr > 0 ? L->ret[0] : NILV;
      if (isnil(first)) break;
      ctl = first;
      for (int i = 0; i < nv; i++) set_local(f, vars[i], i < nr ? L->ret[i] : NILV);
      r = exec_block(L, f, s->blk);
      if (r) { if (r == EX_BREAK) r = EX_OK; break; }
      gc_check(L);
    }
  }
  if (pushed) {
    if (r == EX_RETURN) {
      int n = L->nret; Value *sv = alloca(((size_t)n + 1) * sizeof(Value));
      memcpy(sv, L->ret, (size_t)n * sizeof(Value));
      tbc_close_to(L, base, NILV, 0);
      ret_need(L, n); memcpy(L->ret, sv, (size_t)n * sizeof(Value)); L->nret = n;
    } else tbc_close_to(L, base, NILV, 0);
  }
  return r;
}

static int __attribute__((noinline)) exec_return(State *L, Frame *f, Node *s) {
  int n = s->n;
  if (s->flag) {
    int r = do_call(L, f, s->list[0], 1);
    if (r < 0) return EX_TAIL;
    L->nret = r; return EX_RETURN;
  }
  if (n == 0) { L->nret = 0; return EX_RETURN; }
  if (n == 1 && !is_multi(s->list[0])) {
    Value v = eval(L, f, s->list[0]);
    L->ret[0] = v; L->nret = 1; return EX_RETURN;
  }
  int multi = is_multi(s->list[n - 1]);
  int nf = n - multi;
  need_stack(L, ((size_t)nf + 1) * sizeof(Value));
  Value *t = alloca(((size_t)nf + 1) * sizeof(Value));
  for (int i = 0; i < nf; i++) t[i] = eval(L, f, s->list[i]);
  if (multi) {
    Value *mv; int m = eval_multi(L, f, s->list[n - 1], &mv);
    int viaret = (mv == L->ret);
    ret_need(L, nf + m + 1);
    if (viaret) mv = L->ret;
    memmove(L->ret + nf, mv, (size_t)m * sizeof(Value));
    memcpy(L->ret, t, (size_t)nf * sizeof(Value));
    L->nret = nf + m;
  } else { memcpy(L->ret, t, (size_t)nf * sizeof(Value)); L->nret = nf; }
  return EX_RETURN;
}

static int __attribute__((noinline)) exec_assign(State *L, Frame *f, Node *s) {
  if (s->n == 1 && s->n2 == 1 && !is_multi(s->list2[0])) {
    Node *t = s->list[0];
    switch (t->k) {
      case E_LOCAL: f->slots[t->slot] = eval(L, f, s->list2[0]); return EX_OK;
      case E_BOXED: { Value v = eval(L, f, s->list2[0]); ((Box *)f->slots[t->slot].u.p)->v = v; return EX_OK; }
      case E_FIELD: { Value o = eval(L, f, t->a); Value v = eval(L, f, s->list2[0]); assign_to(L, f, t, o, NILV, v); return EX_OK; }
      case E_INDEX: { Value o = eval(L, f, t->a), k = eval(L, f, t->b); Value v = eval(L, f, s->list2[0]); assign_to(L, f, t, o, k, v); return EX_OK; }
      default: { Value v = eval(L, f, s->list2[0]); assign_to(L, f, t, NILV, NILV, v); return EX_OK; }
    }
  }
  int nt = s->n;
  need_stack(L, (size_t)nt * 3 * sizeof(Value));
  Value *objs = alloca((size_t)nt * 2 * sizeof(Value)), *vals = alloca((size_t)nt * sizeof(Value));
  for (int i = 0; i < nt; i++) {
    Node *t = s->list[i];
    if (t->k == E_FIELD) { objs[2 * i] = eval(L, f, t->a); objs[2 * i + 1] = NILV; }
    else if (t->k == E_INDEX) { objs[2 * i] = eval(L, f, t->a); objs[2 * i + 1] = eval(L, f, t->b); }
    else { objs[2 * i] = NILV; objs[2 * i + 1] = NILV; }
  }
  eval_adjust(L, f, s->list2, s->n2, vals, nt);
  for (int i = nt - 1; i >= 0; i--) assign_to(L, f, s->list[i], objs[2 * i], objs[2 * i + 1], vals[i]);
  return EX_OK;
}

static int __attribute__((noinline)) exec_local(State *L, Frame *f, Node *s) {
  int nv = s->slot; VarInfo **vars = s->u.vars;
  if (nv == 1 && s->n == 1 && !is_multi(s->list[0])) {
    Value v = eval(L, f, s->list[0]);
    set_local(f, vars[0], v);
    if (s->flag && vars[0]->attr == 2) check_close_value(L, f, vars[0], v, s->line);
    return EX_OK;
  }
  need_stack(L, ((size_t)nv + 1) * sizeof(Value));
  Value *tmp = alloca(((size_t)nv + 1) * sizeof(Value));
  if (s->n == 0) for (int i = 0; i < nv; i++) tmp[i] = NILV;
  else eval_adjust(L, f, s->list, s->n, tmp, nv);
  for (int i = 0; i < nv; i++) {
    set_local(f, vars[i], tmp[i]);
    if (s->flag && vars[i]->attr == 2) check_close_value(L, f, vars[i], tmp[i], s->line);
  }
  return EX_OK;
}

static int __attribute__((noinline)) exec_global(State *L, Frame *f, Node *s) {
  int nv = s->slot;
  if (s->n == 0 && !s->list) return EX_OK;
  Value *tmp = alloca(((size_t)nv + 1) * sizeof(Value));
  eval_adjust(L, f, s->list, s->n, tmp, nv);
  for (int i = 0; i < nv; i++) {
    Node *t = s->list2[i];
    Value o = eval(L, f, t->a);
    f->ci->line = s->line;
    int ok; Value cur = index_val(L, o, mkstr(t->name), &ok);
    if (ok && !isnil(cur)) lerror(L, "global '%s' already defined", t->name->data);
    assign_to(L, f, t, o, NILV, tmp[i]);
  }
  return EX_OK;
}

static int exec_stmt(State *L, Frame *f, Node *s) {
  switch (s->k) {
    case S_CALL: do_call(L, f, s->a, 0); return EX_OK;
    case S_LOCAL: return exec_local(L, f, s);
    case S_ASSIGN: return exec_assign(L, f, s);
    case S_IF:
      for (;;) {
        if (cond(L, f, s->a)) return exec_block(L, f, s->blk);
        s = s->b;
        if (!s) return EX_OK;
        if (s->k == S_DO) return exec_block(L, f, s->blk);
      }
    case S_WHILE:
      while (cond(L, f, s->a)) {
        int r = exec_block(L, f, s->blk);
        if (r) { if (r == EX_BREAK) break; return r; }
        gc_check(L);
      }
      return EX_OK;
    case S_REPEAT:
      for (;;) {
        int r = exec_block(L, f, s->blk);
        if (r) { if (r == EX_BREAK) break; return r; }
        if (cond(L, f, s->a)) break;
        gc_check(L);
      }
      return EX_OK;
    case S_FORNUM: return exec_fornum(L, f, s);
    case S_FORIN: return exec_forin(L, f, s);
    case S_DO: return exec_block(L, f, s->blk);
    case S_RETURN: return exec_return(L, f, s);
    case S_BREAK: return EX_BREAK;
    case S_GOTO: goto_target = s->u.lbl; return EX_GOTO;
    case S_LABEL: return EX_OK;
    case S_LOCALFUNC: {
      VarInfo *vi = s->u.vi;
      if (vi->captured) {
        Box *b = box_new(NILV);
        f->slots[vi->slot] = mkobj(T_BOX, b);
        b->v = mkclosure(L, f, s->a->u.p);
      } else f->slots[vi->slot] = mkclosure(L, f, s->a->u.p);
      return EX_OK;
    }
    case S_GLOBAL: return exec_global(L, f, s);
    case S_GLOBALFUNC: {
      Node *t = s->a;
      Value o = eval(L, f, t->a);
      f->ci->line = s->line;
      int ok; Value cur = index_val(L, o, mkstr(t->name), &ok);
      if (ok && !isnil(cur)) lerror(L, "global '%s' already defined", t->name->data);
      assign_to(L, f, t, o, NILV, mkclosure(L, f, s->b->u.p));
      return EX_OK;
    }
    default: lerror(L, "internal error: bad statement node %d", s->k);
  }
}

static int exec_stmts(State *L, Frame *f, Block *b) {
  int i = 0, n = b->n;
  Node **st = b->stmts;
  while (i < n) {
    int r = exec_stmt(L, f, st[i]);
    if (r) {
      if (r == EX_GOTO && b->nlabels) {
        int found = 0;
        for (int j = 0; j < b->nlabels; j++) if (b->labels[j] == goto_target) { i = b->labels[j]->idx; found = 1; break; }
        if (found) { gc_check(L); continue; }
      }
      return r;
    }
    i++;
  }
  return EX_OK;
}
static int __attribute__((noinline)) exec_block_close(State *L, Frame *f, Block *b) {
  int base = L->ntbc;
  int r = exec_stmts(L, f, b);
  if (L->ntbc > base) {
    if (r == EX_RETURN) {
      int n = L->nret; Value *sv = alloca(((size_t)n + 1) * sizeof(Value));
      memcpy(sv, L->ret, (size_t)n * sizeof(Value));
      tbc_close_to(L, base, NILV, 0);
      ret_need(L, n); memcpy(L->ret, sv, (size_t)n * sizeof(Value)); L->nret = n;
    } else tbc_close_to(L, base, NILV, 0);
  }
  return r;
}
static int exec_block(State *L, Frame *f, Block *b) {
  if (b->hasclose) return exec_block_close(L, f, b);
  return exec_stmts(L, f, b);
}

/* ---------- chunk loading ---------- */
Closure *load_chunk(State *L, const char *src, size_t len, const char *chunkname, Value env, char *mode, Value *errmsg) {
  if (mode && !strchr(mode, 't')) {
    *errmsg = mkstr(str_fmt("attempt to load a text chunk (mode is '%s')", mode));
    return NULL;
  }
  Proto *p = parse_chunk(L, src, len, chunkname, errmsg);
  if (!p) return NULL;
  Closure *c = closure_new(p, p->nup);
  c->upv[0] = box_new(env);
  return c;
}

/* ---------- traceback ---------- */
const char *fn_display_name(CFn *c) { return c->name ? c->name : "?"; }

static void describe_ci(CallInfo *ci, char *out, size_t sz) {
  if (ci->cf) { snprintf(out, sz, "[C]: in function '%s'", fn_display_name(ci->cf)); return; }
  char src[80]; short_src_of(ci, src, sizeof src);
  Proto *p = ci->cl->p;
  char what[200];
  Node *cn = ci->callnode;
  if (p->line == 0) snprintf(what, sizeof what, "main chunk");
  else if (cn && !ci->istail) {
    Node *fe = cn->k == E_METH ? cn : cn->a;
    if (fe->k == E_FIELD && (fe->flag & 1)) snprintf(what, sizeof what, "function '%s'", fe->name->data);
    else if (cn->k == E_METH) snprintf(what, sizeof what, "method '%s'", cn->name->data);
    else if (fe->k == E_FIELD) snprintf(what, sizeof what, "field '%s'", fe->name->data);
    else if (fe->k == E_LOCAL || fe->k == E_BOXED) snprintf(what, sizeof what, "local '%s'", fe->name->data);
    else if (fe->k == E_UPVAL) snprintf(what, sizeof what, "upvalue '%s'", fe->name->data);
    else snprintf(what, sizeof what, "function <%s:%d>", src, p->line);
  } else snprintf(what, sizeof what, "function <%s:%d>", src, p->line);
  snprintf(out, sz, "%s:%d: in %s", src, ci->line, what);
}

Str *traceback_str(State *L, const char *msg, int level) {
  size_t cap = 4096, n = 0; char *buf = malloc(cap);
  #define APPEND(...) do { char tmp[400]; int l = snprintf(tmp, sizeof tmp, __VA_ARGS__); if (l < 0) l = 0; if (l > (int)sizeof tmp - 1) l = sizeof tmp - 1; \
    if (n + (size_t)l + 1 > cap) { cap = (n + (size_t)l) * 2; buf = realloc(buf, cap); } memcpy(buf + n, tmp, (size_t)l); n += (size_t)l; } while (0)
  if (msg) APPEND("%s\n", msg);
  APPEND("stack traceback:");
  CallInfo *ci = L->ci;
  while (level-- > 0 && ci) ci = ci->prev;
  int total = 0; for (CallInfo *c = ci; c; c = c->prev) total++;
  int i = 0;
  for (CallInfo *c = ci; c; c = c->prev, i++) {
    if (total > 22 && i == 10) { APPEND("\n\t...\t(skipping %d levels)", total - 21); }
    if (total > 22 && i >= 10 && i < total - 11) continue;
    char d[300]; describe_ci(c, d, sizeof d);
    APPEND("\n\t%s", d);
  }
  if (L->is_main) APPEND("\n\t[C]: in ?");
  Str *s = str_new(buf, n); free(buf);
  return s;
}

void interp_init(State *L) {
  static const char *const names[TM_N] = { "__index", "__newindex", "__gc", "__mode", "__len", "__eq", "__add", "__sub",
    "__mul", "__mod", "__pow", "__div", "__idiv", "__band", "__bor", "__bxor", "__shl", "__shr", "__unm", "__bnot",
    "__lt", "__le", "__concat", "__call", "__close", "__tostring", "__name", "__pairs", "__metatable" };
  for (int i = 0; i < TM_N; i++) G.tmname[i] = str_newz(names[i]);
  (void)L;
}
Value make_closure_main(State *L, Proto *p, Value env) {
  (void)L; Closure *c = closure_new(p, p->nup); c->upv[0] = box_new(env); return mkobj(T_LCL, c);
}
