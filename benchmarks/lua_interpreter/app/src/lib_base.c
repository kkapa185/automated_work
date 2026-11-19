/* Base library + argument-checking helpers. */
#include "lua.h"
#include <ctype.h>
#include <errno.h>

/* ---------- argument helpers ---------- */
void arg_error(State *L, int i, const char *msg) {
  extern Node for_iter_marker;
  const char *fname = L->ci && L->ci->cf ? fn_display_name(L->ci->cf) : "?";
  if (L->ci && L->ci->callnode == &for_iter_marker) fname = "for iterator";
  lerror(L, "bad argument #%d to '%s' (%s)", i + 1, fname, msg);
}
void arg_typeerror(State *L, int i, const char *tname, Value *a, int n) {
  char buf[200];
  snprintf(buf, sizeof buf, "%s expected, got %s", tname, i >= n ? "no value" : objtypename(a[i]));
  arg_error(L, i, buf);
}
lint arg_int(State *L, Value *a, int n, int i) {
  if (i < n) {
    lint r;
    if (a[i].t == T_INT) return a[i].u.i;
    Value x;
    if (tonumber_v(a[i], &x)) {
      if (tointeger_num(x, &r)) return r;
      arg_error(L, i, "number has no integer representation");
    }
  }
  arg_typeerror(L, i, "number", a, n);
}
lint arg_optint(State *L, Value *a, int n, int i, lint def) { return i >= n || isnil(a[i]) ? def : arg_int(L, a, n, i); }
lnum arg_num(State *L, Value *a, int n, int i) {
  Value x;
  if (i < n && tonumber_v(a[i], &x)) return x.t == T_INT ? (lnum)x.u.i : x.u.n;
  arg_typeerror(L, i, "number", a, n);
}
lnum arg_optnum(State *L, Value *a, int n, int i, lnum def) { return i >= n || isnil(a[i]) ? def : arg_num(L, a, n, i); }
Str *arg_str(State *L, Value *a, int n, int i) {
  if (i < n) {
    if (a[i].t == T_STR) return strof(a[i]);
    if (isnum(a[i])) { Value s = tostring_basic(a[i]); a[i] = s; return strof(s); }
  }
  arg_typeerror(L, i, "string", a, n);
}
Table *arg_table(State *L, Value *a, int n, int i) {
  if (i < n && a[i].t == T_TABLE) return tabof(a[i]);
  arg_typeerror(L, i, "table", a, n);
}
void arg_any(State *L, Value *a, int n, int i) { if (i >= n) arg_error(L, i, "value expected"); }

/* ---------- buffers / table access helpers ---------- */
void lbuf_init(LBuf *b) { b->p = NULL; b->n = b->cap = 0; }
static void lbuf_need(LBuf *b, size_t extra) {
  if (b->n + extra + 1 > b->cap) {
    size_t nc = (b->n + extra + 1) * 2; if (nc < 64) nc = 64;
    char *np = realloc(b->p, nc);
    if (!np) { fputs("lua: not enough memory\n", stderr); exit(1); }
    b->p = np; b->cap = nc;
  }
}
void lbuf_add(LBuf *b, const char *s, size_t l) { lbuf_need(b, l); memcpy(b->p + b->n, s, l); b->n += l; }
void lbuf_addc(LBuf *b, char c) { lbuf_need(b, 1); b->p[b->n++] = c; }
Value lbuf_finish(LBuf *b) { Str *s = str_new(b->p ? b->p : "", b->n); free(b->p); b->p = NULL; return mkstr(s); }
void lbuf_free(LBuf *b) { free(b->p); b->p = NULL; }
Value geti_v(State *L, Value t, lint i) {
  if (t.t == T_TABLE && !tabof(t)->meta) return tab_getint(tabof(t), i);
  int ok; Value v = index_val(L, t, mkint(i), &ok);
  if (!ok) lerror(L, "attempt to index a %s value", objtypename(t));
  return v;
}
void seti_v(State *L, Value t, lint i, Value v) {
  if (t.t == T_TABLE && !tabof(t)->meta) { tab_setint(L, tabof(t), i, v); return; }
  Value bad;
  if (!setindex_val(L, t, mkint(i), v, &bad)) lerror(L, "attempt to index a %s value", objtypename(bad));
}

/* ---------- registration ---------- */
void reg_ufunc(Table *t, const char *name, CFunc f, int nup, Value *ups) {
  CFn *c = cfn_new(f, name, nup);
  for (int i = 0; i < nup; i++) c->up[i] = ups[i];
  tab_setstr(NULL, t, str_newz(name), mkobj(T_CFN, c));
}
void reg_func(Table *t, const char *name, CFunc f) { reg_ufunc(t, name, f, 0, NULL); }
Table *reg_lib(State *L, const char *name) {
  (void)L;
  Table *t = tab_new(0, 16);
  tab_setstr(NULL, G.globals, str_newz(name), mktab(t));
  tab_setstr(NULL, G.loaded, str_newz(name), mktab(t));
  return t;
}

/* ---------- base functions ---------- */
static int b_print(State *L, Value *a, int n) {
  (void)L;
  for (int i = 0; i < n; i++) {
    Value s = tostring_meta(L, a[i]);
    if (i) fputc('\t', stdout);
    fwrite(strof(s)->data, 1, strof(s)->len, stdout);
  }
  fputc('\n', stdout);
  return 0;
}
static int b_type(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  return ret1(L, mkstr(str_newz(typename_of(a[0].t))));
}
static int b_tostring(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  return ret1(L, tostring_meta(L, a[0]));
}
static int b_tonumber(State *L, Value *a, int n) {
  if (n < 2 || isnil(a[1])) {
    arg_any(L, a, n, 0);
    Value r;
    if (isnum(a[0])) return ret1(L, a[0]);
    if (a[0].t == T_STR && str2number(strof(a[0])->data, strof(a[0])->len, &r)) return ret1(L, r);
    return ret1(L, NILV);
  }
  lint base = arg_int(L, a, n, 1);
  if (a[0].t != T_STR) arg_typeerror(L, 0, "string", a, n);
  if (base < 2 || base > 36) arg_error(L, 1, "base out of range");
  const char *s = strof(a[0])->data, *e = s + strof(a[0])->len;
  while (s < e && isspace((unsigned char)*s)) s++;
  while (e > s && isspace((unsigned char)e[-1])) e--;
  int neg = 0;
  if (s < e && *s == '-') { neg = 1; s++; } else if (s < e && *s == '+') s++;
  if (s == e) return ret1(L, NILV);
  luint v = 0;
  for (; s < e; s++) {
    int d;
    if (isdigit((unsigned char)*s)) d = *s - '0';
    else if (isalpha((unsigned char)*s)) d = tolower((unsigned char)*s) - 'a' + 10;
    else return ret1(L, NILV);
    if (d >= base) return ret1(L, NILV);
    v = v * (luint)base + (luint)d;
  }
  return ret1(L, mkint((lint)(neg ? (luint)0 - v : v)));
}
static int b_next(State *L, Value *a, int n) {
  Table *t = arg_table(L, a, n, 0);
  Value k = argv(a, n, 1), v;
  if (tab_next(L, t, &k, &v)) { L->ret[0] = k; L->ret[1] = v; return 2; }
  return ret1(L, NILV);
}
static int b_pairs(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  Value tm = get_tm(a[0], TM_PAIRS);
  if (!isnil(tm)) {
    Value args[1] = {a[0]};
    int r = call_value(L, tm, args, 1);
    for (int i = r; i < 3; i++) L->ret[i] = NILV;
    return 3;
  }
  L->ret[0] = mkobj(T_CFN, G.next_fn); L->ret[1] = a[0]; L->ret[2] = NILV;
  return 3;
}
static int ipairs_iter(State *L, Value *a, int n) {
  lint i = arg_int(L, a, n, 1) + 1;
  Value v;
  if (a[0].t == T_TABLE && !tabof(a[0])->meta) v = tab_getint(tabof(a[0]), i);
  else { int ok; v = index_val(L, a[0], mkint(i), &ok); if (!ok) lerror(L, "attempt to index a %s value", objtypename(a[0])); }
  if (isnil(v)) return ret1(L, NILV);
  L->ret[0] = mkint(i); L->ret[1] = v; return 2;
}
static int b_ipairs(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  L->ret[0] = mkobj(T_CFN, G.ipairs_iter); L->ret[1] = a[0]; L->ret[2] = mkint(0);
  return 3;
}
static int b_select(State *L, Value *a, int n) {
  if (n >= 1 && a[0].t == T_STR && strof(a[0])->len == 1 && strof(a[0])->data[0] == '#') return ret1(L, mkint(n - 1));
  lint i = arg_int(L, a, n, 0);
  if (i < 0) i = n + i;
  else if (i > n) i = n;
  if (i < 1) arg_error(L, 0, "index out of range");
  int cnt = n - (int)i;
  ret_need(L, cnt + 1);
  memmove(L->ret, a + i, (size_t)cnt * sizeof(Value));
  return cnt;
}
static int b_rawget(State *L, Value *a, int n) { Table *t = arg_table(L, a, n, 0); arg_any(L, a, n, 1); return ret1(L, tab_get(t, a[1])); }
static int b_rawset(State *L, Value *a, int n) {
  Table *t = arg_table(L, a, n, 0); arg_any(L, a, n, 1); arg_any(L, a, n, 2);
  tab_set(L, t, a[1], a[2]); return ret1(L, a[0]);
}
static int b_rawequal(State *L, Value *a, int n) { arg_any(L, a, n, 0); arg_any(L, a, n, 1); return ret1(L, mkbool(raw_equal(a[0], a[1]))); }
static int b_rawlen(State *L, Value *a, int n) {
  if (n >= 1 && a[0].t == T_TABLE) return ret1(L, mkint(tab_len(tabof(a[0]))));
  if (n >= 1 && a[0].t == T_STR) return ret1(L, mkint((lint)strof(a[0])->len));
  arg_error(L, 0, "table or string expected");
}
static int b_setmetatable(State *L, Value *a, int n) {
  Table *t = arg_table(L, a, n, 0);
  if (n < 2 || (a[1].t != T_TABLE && a[1].t != T_NIL)) arg_typeerror(L, 1, "nil or table", a, n);
  if (t->meta && !isnil(tab_getstr(t->meta, G.tmname[TM_METATABLE]))) lerror(L, "cannot change a protected metatable");
  t->meta = a[1].t == T_NIL ? NULL : tabof(a[1]);
  return ret1(L, a[0]);
}
static int b_getmetatable(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  Table *mt = getmetatable_of(a[0]);
  if (!mt) return ret1(L, NILV);
  Value p = tab_getstr(mt, G.tmname[TM_METATABLE]);
  if (!isnil(p)) return ret1(L, p);
  return ret1(L, mktab(mt));
}
static int b_assert(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  if (truthy(a[0])) { ret_need(L, n); memmove(L->ret, a, (size_t)n * sizeof(Value)); return n; }
  if (n >= 2) lua_throw(L, a[1]);
  lerror(L, "assertion failed!");
}
static int b_error(State *L, Value *a, int n) {
  Value v = argv(a, n, 0);
  lint level = arg_optint(L, a, n, 1, 1);
  if (v.t == T_STR && level > 0) {
    Str *w = where_str(L, (int)level);
    if (w->len) {
      size_t tl = w->len + strof(v)->len; char *tmp = malloc(tl + 1);
      memcpy(tmp, w->data, w->len); memcpy(tmp + w->len, strof(v)->data, strof(v)->len);
      v = mkstr(str_new(tmp, tl)); free(tmp);
    }
  }
  lua_throw(L, v);
}
static int b_pcall(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  ErrJmp ej; memset(&ej, 0, sizeof ej);
  ej.prev = L->ej; ej.handler = NILV; ej.ci = L->ci; ej.depth = L->depth; ej.ntbc = L->ntbc;
  L->ej = &ej;
  if (setjmp(ej.jb) == 0) {
    int r = call_value(L, a[0], a + 1, n - 1);
    L->ej = ej.prev;
    ret_need(L, r + 1);
    memmove(L->ret + 1, L->ret, (size_t)r * sizeof(Value));
    L->ret[0] = mkbool(1);
    return r + 1;
  }
  L->ej = ej.prev; L->ci = ej.ci; L->depth = ej.depth;
  Value err = tbc_unwind(L, ej.ntbc, ej.err);
  L->ret[0] = mkbool(0); L->ret[1] = err;
  return 2;
}
static int b_xpcall(State *L, Value *a, int n) {
  if (n < 2) arg_typeerror(L, 1, "function", a, n);
  ErrJmp ej; memset(&ej, 0, sizeof ej);
  ej.prev = L->ej; ej.handler = a[1]; ej.ci = L->ci; ej.depth = L->depth; ej.ntbc = L->ntbc;
  L->ej = &ej;
  if (setjmp(ej.jb) == 0) {
    int r = call_value(L, a[0], a + 2, n - 2);
    L->ej = ej.prev;
    ret_need(L, r + 1);
    memmove(L->ret + 1, L->ret, (size_t)r * sizeof(Value));
    L->ret[0] = mkbool(1);
    return r + 1;
  }
  L->ej = ej.prev; L->ci = ej.ci; L->depth = ej.depth;
  Value err = tbc_unwind(L, ej.ntbc, ej.err);
  L->ret[0] = mkbool(0); L->ret[1] = err;
  return 2;
}
static int b_collectgarbage(State *L, Value *a, int n) {
  const char *opt = n >= 1 && !isnil(a[0]) ? arg_str(L, a, n, 0)->data : "collect";
  if (!strcmp(opt, "collect")) { gc_collect(L); return ret1(L, mkint(0)); }
  if (!strcmp(opt, "count")) { double kb = (double)G.bytes / 1024.0; return ret1(L, mkflt(kb)); }
  if (!strcmp(opt, "step")) { gc_collect(L); return ret1(L, mkbool(1)); }
  if (!strcmp(opt, "isrunning")) return ret1(L, mkbool(!G.gcstop));
  if (!strcmp(opt, "stop")) { G.gcstop = 1; return ret1(L, mkint(0)); }
  if (!strcmp(opt, "restart")) { G.gcstop = 0; return ret1(L, mkint(0)); }
  if (!strcmp(opt, "incremental") || !strcmp(opt, "generational")) {
    static const char *mode = "incremental";
    const char *old = mode; mode = opt;
    return ret1(L, mkstr(str_newz(old)));
  }
  if (!strcmp(opt, "setpause") || !strcmp(opt, "setstepmul")) return ret1(L, mkint(100));
  char buf[100]; snprintf(buf, sizeof buf, "invalid option '%s'", opt);
  arg_error(L, 0, buf);
}

static char *read_file(const char *path, size_t *len) {
  FILE *fp = strcmp(path, "-") == 0 ? stdin : fopen(path, "rb");
  if (!fp) return NULL;
  size_t cap = 4096, n = 0; char *buf = malloc(cap);
  for (;;) {
    size_t r = fread(buf + n, 1, cap - n, fp);
    n += r;
    if (n < cap) break;
    cap *= 2; buf = realloc(buf, cap);
  }
  if (fp != stdin) fclose(fp);
  *len = n; return buf;
}
static int do_load(State *L, const char *src, size_t len, const char *name, Value env, char *mode) {
  Value err;
  Closure *c = load_chunk(L, src, len, name, env, mode, &err);
  if (!c) { L->ret[0] = NILV; L->ret[1] = err; return 2; }
  return ret1(L, mkobj(T_LCL, c));
}
static int b_load(State *L, Value *a, int n) {
  Value env = n >= 4 ? a[3] : mktab(G.globals);
  char *mode = NULL; char mbuf[8];
  if (n >= 3 && !isnil(a[2])) { Str *m = arg_str(L, a, n, 2); snprintf(mbuf, sizeof mbuf, "%s", m->data); mode = mbuf; }
  if (n >= 1 && a[0].t == T_STR) {
    Str *s = strof(a[0]);
    const char *name = n >= 2 && !isnil(a[1]) ? arg_str(L, a, n, 1)->data : s->data;
    return do_load(L, s->data, s->len, name, env, mode);
  }
  if (n < 1 || (a[0].t != T_LCL && a[0].t != T_CFN)) arg_typeerror(L, 0, "function", a, n);
  const char *name = n >= 2 && !isnil(a[1]) ? arg_str(L, a, n, 1)->data : "=(load)";
  size_t cap = 256, len = 0; char *buf = malloc(cap);
  for (;;) {
    Value rerr;
    int r = protected_call(L, a[0], NULL, 0, &rerr);
    if (r < 0) { free(buf); L->ret[0] = NILV; L->ret[1] = rerr; return 2; }
    if (r < 1 || isnil(L->ret[0])) break;
    if (L->ret[0].t != T_STR) { free(buf); L->ret[0] = NILV; L->ret[1] = mkstr(str_newz("reader function must return a string")); return 2; }
    Str *p = strof(L->ret[0]);
    if (p->len == 0) break;
    if (len + p->len > cap) { cap = (len + p->len) * 2; buf = realloc(buf, cap); }
    memcpy(buf + len, p->data, p->len); len += p->len;
  }
  int r = do_load(L, buf, len, name, env, mode);
  free(buf);
  return r;
}
static int load_file_impl(State *L, const char *fname, Value env, char *mode) {
  size_t len; char *buf = read_file(fname, &len);
  if (!buf) {
    char m[300]; snprintf(m, sizeof m, "cannot open %s", fname);
    L->ret[0] = NILV; L->ret[1] = mkstr(str_newz(m)); return 2;
  }
  char cn[600]; snprintf(cn, sizeof cn, "@%s", strcmp(fname, "-") ? fname : "stdin");
  int r = do_load(L, buf, len, cn, env, mode);
  free(buf);
  return r;
}
static int b_loadfile(State *L, Value *a, int n) {
  const char *fname = n >= 1 && !isnil(a[0]) ? arg_str(L, a, n, 0)->data : "-";
  char *mode = NULL; char mbuf[8];
  if (n >= 2 && !isnil(a[1])) { snprintf(mbuf, sizeof mbuf, "%s", arg_str(L, a, n, 1)->data); mode = mbuf; }
  return load_file_impl(L, fname, n >= 3 ? a[2] : mktab(G.globals), mode);
}
static int b_dofile(State *L, Value *a, int n) {
  const char *fname = n >= 1 && !isnil(a[0]) ? arg_str(L, a, n, 0)->data : "-";
  int r = load_file_impl(L, fname, mktab(G.globals), NULL);
  if (isnil(L->ret[0])) lua_throw(L, L->ret[1]);
  (void)r;
  Value fn = L->ret[0];
  return call_value(L, fn, NULL, 0);
}

static int warn_on = 0;
static int b_warn(State *L, Value *a, int n) {
  arg_str(L, a, n, 0);
  for (int i = 1; i < n; i++) arg_str(L, a, n, i);
  if (n == 1 && strof(a[0])->len > 0 && strof(a[0])->data[0] == '@') {
    if (!strcmp(strof(a[0])->data, "@on")) warn_on = 1; else if (!strcmp(strof(a[0])->data, "@off")) warn_on = 0;
    return 0;
  }
  if (warn_on) {
    fflush(stdout);
    fputs("Lua warning: ", stderr);
    for (int i = 0; i < n; i++) fwrite(strof(a[i])->data, 1, strof(a[i])->len, stderr);
    fputc('\n', stderr);
  }
  return 0;
}

void open_base(State *L) {
  Table *g = G.globals;
  tab_setstr(L, g, str_newz("_G"), mktab(g));
  tab_setstr(L, g, str_newz("_VERSION"), mkstr(str_newz("Lua 5.5")));
  reg_func(g, "print", b_print); reg_func(g, "type", b_type); reg_func(g, "tostring", b_tostring);
  reg_func(g, "tonumber", b_tonumber); reg_func(g, "pairs", b_pairs); reg_func(g, "ipairs", b_ipairs);
  reg_func(g, "select", b_select); reg_func(g, "rawget", b_rawget); reg_func(g, "rawset", b_rawset);
  reg_func(g, "rawequal", b_rawequal); reg_func(g, "rawlen", b_rawlen);
  reg_func(g, "setmetatable", b_setmetatable); reg_func(g, "getmetatable", b_getmetatable);
  reg_func(g, "assert", b_assert); reg_func(g, "error", b_error); reg_func(g, "pcall", b_pcall);
  reg_func(g, "xpcall", b_xpcall); reg_func(g, "collectgarbage", b_collectgarbage);
  reg_func(g, "load", b_load); reg_func(g, "loadfile", b_loadfile); reg_func(g, "dofile", b_dofile);
  reg_func(g, "next", b_next); reg_func(g, "warn", b_warn);
  G.next_fn = (CFn *)tab_getstr(g, str_newz("next")).u.p;
  G.ipairs_iter = cfn_new(ipairs_iter, "ipairs_iter", 0);
}
