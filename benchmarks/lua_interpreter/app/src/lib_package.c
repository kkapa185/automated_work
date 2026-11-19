/* package/require and the debug library (minimal). */
#include "lua.h"
#include <errno.h>

static Table *pkg;
static Value pkgfield(const char *name) { return tab_getstr(pkg, str_newz(name)); }

static int readable(const char *f) { FILE *fp = fopen(f, "r"); if (fp) { fclose(fp); return 1; } return 0; }

static Value search_path(State *L, const char *name, const char *path, const char *sep, const char *rep, LBuf *msg) {
  size_t ln = strlen(name), ls = strlen(sep), lr = strlen(rep);
  LBuf nm; lbuf_init(&nm);
  if (*sep) {
    const char *p = name;
    while (p < name + ln) {
      if (ls && strncmp(p, sep, ls) == 0) { lbuf_add(&nm, rep, lr); p += ls; } else lbuf_addc(&nm, *p++);
    }
  } else lbuf_add(&nm, name, ln);
  lbuf_addc(&nm, 0);
  const char *p = path; int first = 1;
  while (*p) {
    const char *e = strchr(p, ';'); if (!e) e = p + strlen(p);
    if (e > p) {
      LBuf fn; lbuf_init(&fn);
      for (const char *q = p; q < e; q++) { if (*q == '?') lbuf_add(&fn, nm.p, strlen(nm.p)); else lbuf_addc(&fn, *q); }
      lbuf_addc(&fn, 0);
      if (readable(fn.p)) { Value r = mkstr(str_newz(fn.p)); lbuf_free(&fn); lbuf_free(&nm); return r; }
      if (msg) {
        if (!first) lbuf_add(msg, "\n\t", 2);
        lbuf_add(msg, "no file '", 9); lbuf_add(msg, fn.p, strlen(fn.p)); lbuf_addc(msg, '\'');
        first = 0;
      }
      lbuf_free(&fn);
    }
    p = *e ? e + 1 : e;
  }
  lbuf_free(&nm);
  (void)L;
  return NILV;
}
static int p_searchpath(State *L, Value *a, int n) {
  const char *name = arg_str(L, a, n, 0)->data, *path = arg_str(L, a, n, 1)->data;
  const char *sep = n >= 3 && !isnil(a[2]) ? arg_str(L, a, n, 2)->data : ".";
  const char *rep = n >= 4 && !isnil(a[3]) ? arg_str(L, a, n, 3)->data : "/";
  LBuf msg; lbuf_init(&msg);
  Value r = search_path(L, name, path, sep, rep, &msg);
  if (!isnil(r)) { lbuf_free(&msg); return ret1(L, r); }
  L->ret[0] = NILV; L->ret[1] = lbuf_finish(&msg); return 2;
}
static int searcher_preload(State *L, Value *a, int n) {
  Str *name = arg_str(L, a, n, 0);
  Value pre = pkgfield("preload");
  if (pre.t != T_TABLE) lerror(L, "'package.preload' must be a table");
  Value v = tab_getstr(tabof(pre), name);
  if (isnil(v)) return ret1(L, mkstr(str_fmt("no field package.preload['%s']", name->data)));
  L->ret[0] = v; L->ret[1] = mkstr(str_newz(":preload:")); return 2;
}
static int searcher_lua(State *L, Value *a, int n) {
  Str *name = arg_str(L, a, n, 0);
  Value path = pkgfield("path");
  if (path.t != T_STR) lerror(L, "'package.path' must be a string");
  LBuf msg; lbuf_init(&msg);
  Value fn = search_path(L, name->data, strof(path)->data, ".", "/", &msg);
  if (isnil(fn)) return ret1(L, lbuf_finish(&msg));
  lbuf_free(&msg);
  FILE *fp = fopen(strof(fn)->data, "rb");
  LBuf src; lbuf_init(&src); char tmp[4096]; size_t r;
  while ((r = fread(tmp, 1, sizeof tmp, fp)) > 0) lbuf_add(&src, tmp, r);
  fclose(fp);
  char cn[1100]; snprintf(cn, sizeof cn, "@%s", strof(fn)->data);
  Value err;
  Closure *c = load_chunk(L, src.p ? src.p : "", src.n, cn, mktab(G.globals), NULL, &err);
  lbuf_free(&src);
  if (!c) lerror(L, "error loading module '%s' from file '%s':\n\t%s", name->data, strof(fn)->data, strof(err)->data);
  L->ret[0] = mkobj(T_LCL, c); L->ret[1] = fn; return 2;
}
static int g_require(State *L, Value *a, int n) {
  Str *name = arg_str(L, a, n, 0);
  Value loadedv = pkgfield("loaded");
  if (loadedv.t != T_TABLE) lerror(L, "'package.loaded' must be a table");
  Table *loaded = tabof(loadedv);
  Value v = tab_getstr(loaded, name);
  if (truthy(v)) return ret1(L, v);
  Value searchers = pkgfield("searchers");
  if (searchers.t != T_TABLE) lerror(L, "'package.searchers' must be a table");
  LBuf msg; lbuf_init(&msg);
  Value loader = NILV, extra = NILV;
  for (lint i = 1;; i++) {
    Value s = tab_getint(tabof(searchers), i);
    if (isnil(s)) {
      char *m = msg.p ? msg.p : "";
      lbuf_addc(&msg, 0);
      Str *e = str_fmt("module '%s' not found:%s", name->data, m);
      lbuf_free(&msg);
      lua_throw(L, mkstr(e));
    }
    Value args[1] = {mkstr(name)};
    int r = call_value(L, s, args, 1);
    Value r0 = r > 0 ? L->ret[0] : NILV, r1 = r > 1 ? L->ret[1] : NILV;
    if (r0.t == T_LCL || r0.t == T_CFN) { loader = r0; extra = r1; break; }
    if (r0.t == T_STR) { lbuf_add(&msg, "\n\t", 2); lbuf_add(&msg, strof(r0)->data, strof(r0)->len); }
  }
  lbuf_free(&msg);
  Value largs[2] = {mkstr(name), extra};
  int r = call_value(L, loader, largs, 2);
  Value res = r > 0 ? L->ret[0] : NILV;
  if (!isnil(res)) tab_setstr(L, loaded, name, res);
  else if (isnil(tab_getstr(loaded, name))) tab_setstr(L, loaded, name, mkbool(1));
  L->ret[0] = tab_getstr(loaded, name); L->ret[1] = extra;
  return 2;
}
static int p_loadlib(State *L, Value *a, int n) {
  L->ret[0] = NILV; L->ret[1] = mkstr(str_newz("dynamic libraries not enabled; check your Lua installation")); L->ret[2] = mkstr(str_newz("absent"));
  return 3;
}

/* ---------- debug ---------- */
static State *dbg_thread(State *L, Value *a, int n, int *arg) {
  if (n >= 1 && a[0].t == T_THREAD) { *arg = 1; return (State *)a[0].u.p; }
  *arg = 0; return L;
}
static int d_traceback(State *L, Value *a, int n) {
  int arg; State *T = dbg_thread(L, a, n, &arg);
  Value msg = argv(a, n, arg);
  if (!isnil(msg) && msg.t != T_STR && !isnum(msg)) return ret1(L, msg);
  lint level = arg_optint(L, a, n, arg + 1, T == L ? 1 : 0);
  const char *m = NULL;
  if (!isnil(msg)) { Value s = tostring_basic(msg); a[arg] = s; m = strof(s)->data; }
  return ret1(L, mkstr(traceback_str(T, m, (int)level)));
}
static void setstrf(State *L, Table *t, const char *k, const char *v) { tab_setstr(L, t, str_newz(k), mkstr(str_newz(v))); }
static void setintf(State *L, Table *t, const char *k, lint v) { tab_setstr(L, t, str_newz(k), mkint(v)); }
static int d_getinfo(State *L, Value *a, int n) {
  int arg; State *T = dbg_thread(L, a, n, &arg);
  const char *what = n > arg + 1 && !isnil(a[arg + 1]) ? arg_str(L, a, n, arg + 1)->data : "flnSrtu";
  CallInfo *ci = NULL; Value func = NILV;
  if (arg < n && (a[arg].t == T_LCL || a[arg].t == T_CFN)) func = a[arg];
  else {
    lint level = arg_int(L, a, n, arg);
    if (level < 0) return ret1(L, NILV);
    ci = T->ci;
    while (level-- > 0 && ci) ci = ci->prev;
    if (!ci) return ret1(L, NILV);
    func = ci->cl ? mkobj(T_LCL, ci->cl) : mkobj(T_CFN, ci->cf);
  }
  for (const char *w = what; *w; w++) if (!strchr("SlnrutLf>", *w)) arg_error(L, arg + 1, "invalid option");
  Table *t = tab_new(0, 16);
  Closure *cl = func.t == T_LCL ? (Closure *)func.u.p : NULL;
  Proto *p = cl ? cl->p : NULL;
  for (const char *w = what; *w; w++) switch (*w) {
    case 'S':
      if (p) {
        tab_setstr(L, t, str_newz("source"), mkstr(p->chunk->source));
        setstrf(L, t, "short_src", p->chunk->short_src);
        setintf(L, t, "linedefined", p->line); setintf(L, t, "lastlinedefined", p->lastline);
        setstrf(L, t, "what", p->line == 0 ? "main" : "Lua");
      } else {
        setstrf(L, t, "source", "=[C]"); setstrf(L, t, "short_src", "[C]");
        setintf(L, t, "linedefined", -1); setintf(L, t, "lastlinedefined", -1); setstrf(L, t, "what", "C");
      }
      break;
    case 'l': setintf(L, t, "currentline", ci && ci->cl ? ci->line : -1); break;
    case 'u':
      setintf(L, t, "nups", p ? p->nup : (func.t == T_CFN ? ((CFn *)func.u.p)->nup : 0));
      setintf(L, t, "nparams", p ? p->nparams : 0);
      tab_setstr(L, t, str_newz("isvararg"), mkbool(p ? p->is_vararg : 1));
      break;
    case 'n': {
      Node *cn = ci ? ci->callnode : NULL;
      const char *nw = ""; Str *nm = NULL;
      if (cn && !ci->istail) {
        Node *fe = cn->k == E_METH ? cn : cn->a;
        if (cn->k == E_METH) { nw = "method"; nm = cn->name; }
        else if (fe->k == E_FIELD && (fe->flag & 1)) { nw = "global"; nm = fe->name; }
        else if (fe->k == E_FIELD) { nw = "field"; nm = fe->name; }
        else if (fe->k == E_LOCAL || fe->k == E_BOXED) { nw = "local"; nm = fe->name; }
        else if (fe->k == E_UPVAL) { nw = "upvalue"; nm = fe->name; }
      } else if (ci && ci->cf) { nw = "global"; nm = str_newz(fn_display_name(ci->cf)); }
      if (nm) tab_setstr(L, t, str_newz("name"), mkstr(nm));
      setstrf(L, t, "namewhat", nw);
      break;
    }
    case 't': tab_setstr(L, t, str_newz("istailcall"), mkbool(ci && ci->istail)); break;
    case 'r': setintf(L, t, "ftransfer", 0); setintf(L, t, "ntransfer", 0); break;
    case 'f': tab_setstr(L, t, str_newz("func"), func); break;
    default: break;
  }
  return ret1(L, mktab(t));
}
static int d_getlocal(State *L, Value *a, int n) { return ret1(L, NILV); }
static int d_sethook(State *L, Value *a, int n) { return 0; }
static int d_gethook(State *L, Value *a, int n) { return ret1(L, NILV); }
static int d_getmetatable(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  Table *mt = getmetatable_of(a[0]);
  return ret1(L, mt ? mktab(mt) : NILV);
}
static int d_setmetatable(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  if (n < 2 || (a[1].t != T_TABLE && a[1].t != T_NIL)) arg_typeerror(L, 1, "nil or table", a, n);
  Table *mt = a[1].t == T_NIL ? NULL : tabof(a[1]);
  if (a[0].t == T_TABLE) tabof(a[0])->meta = mt;
  else if (a[0].t == T_UDATA) ((Udata *)a[0].u.p)->meta = mt;
  else if (a[0].t == T_STR) G.strmeta = mt;
  else lerror(L, "cannot set the metatable of a %s value", typename_of(a[0].t));
  return ret1(L, a[0]);
}
static int d_getregistry(State *L, Value *a, int n) { return ret1(L, mktab(G.registry)); }
static int d_getupvalue(State *L, Value *a, int n) {
  lint i = arg_int(L, a, n, 1);
  if (n < 1 || (a[0].t != T_LCL && a[0].t != T_CFN)) arg_typeerror(L, 0, "function", a, n);
  if (a[0].t == T_LCL) {
    Closure *c = a[0].u.p;
    if (i >= 1 && i <= c->nup) { L->ret[0] = mkstr(c->p->up[i - 1].name); L->ret[1] = c->upv[i - 1]->v; return 2; }
  }
  return 0;
}
static int d_setupvalue(State *L, Value *a, int n) {
  lint i = arg_int(L, a, n, 1); arg_any(L, a, n, 2);
  if (n < 1 || (a[0].t != T_LCL && a[0].t != T_CFN)) arg_typeerror(L, 0, "function", a, n);
  if (a[0].t == T_LCL) {
    Closure *c = a[0].u.p;
    if (i >= 1 && i <= c->nup) { c->upv[i - 1]->v = a[2]; return ret1(L, mkstr(c->p->up[i - 1].name)); }
  }
  return 0;
}

static int d_getuservalue(State *L, Value *a, int n) {
  if (n >= 1 && a[0].t == T_UDATA && arg_optint(L, a, n, 1, 1) == 1) { L->ret[0] = ((Udata *)a[0].u.p)->uv; L->ret[1] = mkbool(1); return 2; }
  return ret1(L, NILV);
}
static int d_setuservalue(State *L, Value *a, int n) {
  if (n < 1 || a[0].t != T_UDATA) arg_typeerror(L, 0, "userdata", a, n);
  arg_any(L, a, n, 1);
  if (arg_optint(L, a, n, 2, 1) != 1) return ret1(L, NILV);
  ((Udata *)a[0].u.p)->uv = a[1];
  return ret1(L, a[0]);
}
static int d_setlocal(State *L, Value *a, int n) { return ret1(L, NILV); }
static Box *upbox(State *L, Value *a, int n, int fi, int ii) {
  if (fi >= n || a[fi].t != T_LCL) arg_typeerror(L, fi, "Lua function", a, n);
  Closure *c = a[fi].u.p; lint i = arg_int(L, a, n, ii);
  if (i < 1 || i > c->nup) arg_error(L, ii, "invalid upvalue index");
  return c->upv[i - 1];
}
static int d_upvalueid(State *L, Value *a, int n) {
  Box *b = upbox(L, a, n, 0, 1);
  Value key = mkint((lint)(uintptr_t)b);
  Value reg = tab_getstr(G.registry, str_newz("_UPVALUEIDS"));
  if (reg.t != T_TABLE) { reg = mktab(tab_new(0, 8)); tab_setstr(L, G.registry, str_newz("_UPVALUEIDS"), reg); }
  Value u = tab_get(tabof(reg), key);
  if (isnil(u)) { u = mkobj(T_UDATA, udata_new()); tab_set(L, tabof(reg), key, u); }
  return ret1(L, u);
}
static int d_upvaluejoin(State *L, Value *a, int n) {
  upbox(L, a, n, 0, 1); upbox(L, a, n, 2, 3);
  ((Closure *)a[0].u.p)->upv[arg_int(L, a, n, 1) - 1] = ((Closure *)a[2].u.p)->upv[arg_int(L, a, n, 3) - 1];
  return 0;
}
static int d_debug(State *L, Value *a, int n) {
  char line[1024];
  for (;;) {
    fputs("lua_debug> ", stderr); fflush(stderr);
    if (!fgets(line, sizeof line, stdin) || strcmp(line, "cont\n") == 0) return 0;
    Value err; Closure *c = load_chunk(L, line, strlen(line), "=(debug command)", mktab(G.globals), NULL, &err);
    if (!c) { fprintf(stderr, "%s\n", strof(err)->data); continue; }
    if (protected_call(L, mkobj(T_LCL, c), NULL, 0, &err) < 0) { Value s = tostring_basic(err); fprintf(stderr, "%s\n", strof(s)->data); }
  }
}

void open_package(State *L) {
  pkg = reg_lib(L, "package");
  const char *env = getenv("LUA_PATH_5_5"); if (!env) env = getenv("LUA_PATH");
  tab_setstr(L, pkg, str_newz("path"), mkstr(str_newz(env ? env : "./?.lua;./?/init.lua")));
  tab_setstr(L, pkg, str_newz("cpath"), mkstr(str_newz("./?.so")));
  tab_setstr(L, pkg, str_newz("config"), mkstr(str_newz("/\n;\n?\n!\n-\n")));
  tab_setstr(L, pkg, str_newz("loaded"), mktab(G.loaded));
  tab_setstr(L, G.loaded, str_newz("_G"), mktab(G.globals));
  tab_setstr(L, pkg, str_newz("preload"), mktab(tab_new(0, 4)));
  Table *sr = tab_new(2, 0);
  tab_setint(L, sr, 1, mkobj(T_CFN, cfn_new(searcher_preload, "searcher_preload", 0)));
  tab_setint(L, sr, 2, mkobj(T_CFN, cfn_new(searcher_lua, "searcher_Lua", 0)));
  tab_setstr(L, pkg, str_newz("searchers"), mktab(sr));
  reg_func(pkg, "searchpath", p_searchpath); reg_func(pkg, "loadlib", p_loadlib);
  reg_func(G.globals, "require", g_require);
  Table *d = reg_lib(L, "debug");
  reg_func(d, "traceback", d_traceback); reg_func(d, "getinfo", d_getinfo); reg_func(d, "getlocal", d_getlocal);
  reg_func(d, "sethook", d_sethook); reg_func(d, "gethook", d_gethook); reg_func(d, "getmetatable", d_getmetatable);
  reg_func(d, "setmetatable", d_setmetatable); reg_func(d, "getregistry", d_getregistry);
  reg_func(d, "getupvalue", d_getupvalue); reg_func(d, "getuservalue", d_getuservalue); reg_func(d, "setuservalue", d_setuservalue); reg_func(d, "setlocal", d_setlocal); reg_func(d, "upvalueid", d_upvalueid); reg_func(d, "upvaluejoin", d_upvaluejoin); reg_func(d, "debug", d_debug); reg_func(d, "setupvalue", d_setupvalue);
}
