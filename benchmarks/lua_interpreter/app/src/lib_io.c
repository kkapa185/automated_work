/* io library: files are userdata wrapping stdio FILE*. */
#include "lua.h"
#include <errno.h>
#include <ctype.h>
#include <sys/wait.h>
#include <alloca.h>

typedef struct LFile { FILE *f; int closed; int kind; } LFile; /* kind: 0 regular, 1 standard, 2 pipe */
static Table *file_meta, *file_methods;
static Value v_meta, v_methods, defin, defout;

static void file_fin(Udata *u) {
  LFile *lf = u->data;
  if (lf) {
    if (!lf->closed) { if (lf->kind == 0) fclose(lf->f); else if (lf->kind == 2) pclose(lf->f); else fflush(lf->f); }
    free(lf); u->data = NULL;
  }
}
static Value new_file(FILE *f, int kind) {
  Udata *u = udata_new();
  LFile *lf = malloc(sizeof *lf); lf->f = f; lf->closed = 0; lf->kind = kind;
  u->data = lf; u->meta = file_meta; u->fin = file_fin;
  return mkobj(T_UDATA, u);
}
static int is_file(Value v) { return v.t == T_UDATA && ((Udata *)v.u.p)->meta == file_meta; }
static LFile *tofile_open(State *L, Value *a, int n, int i) {
  if (!(i < n && is_file(a[i]))) arg_typeerror(L, i, "FILE*", a, n);
  LFile *lf = ((Udata *)a[i].u.p)->data;
  if (!lf || lf->closed) lerror(L, "attempt to use a closed file");
  return lf;
}
static LFile *vfile(Value v) { return ((Udata *)v.u.p)->data; }

static int fileresult(State *L, int ok, const char *fname) {
  int en = errno;
  if (ok) return ret1(L, mkbool(1));
  L->ret[0] = NILV;
  L->ret[1] = mkstr(fname ? str_fmt("%s: %s", fname, strerror(en)) : str_newz(strerror(en)));
  L->ret[2] = mkint(en);
  return 3;
}
static int close_file(State *L, LFile *lf) {
  if (lf->kind == 1) { L->ret[0] = NILV; L->ret[1] = mkstr(str_newz("cannot close standard file")); return 2; }
  lf->closed = 1;
  if (lf->kind == 2) {
    int st = pclose(lf->f);
    if (st == -1) return fileresult(L, 0, NULL);
    const char *what = "exit"; int code = st;
    if (WIFEXITED(st)) code = WEXITSTATUS(st);
    else { what = "signal"; code = st & 0x7f; }
    L->ret[0] = (what[0] == 'e' && code == 0) ? mkbool(1) : NILV;
    L->ret[1] = mkstr(str_newz(what)); L->ret[2] = mkint(code);
    return 3;
  }
  return fileresult(L, fclose(lf->f) == 0, NULL);
}

/* ---------- reading ---------- */
static int read_line(FILE *f, LBuf *b, int chop) {
  int c = 0;
  while ((c = getc(f)) != EOF && c != '\n') lbuf_addc(b, (char)c);
  if (!chop && c == '\n') lbuf_addc(b, '\n');
  return c == '\n' || b->n > 0;
}
typedef struct RN { FILE *f; int c; int n; char buff[201]; } RN;
static int rn_next(RN *rn) {
  if (rn->n >= 200) { rn->buff[0] = 0; return 0; }
  rn->buff[rn->n++] = (char)rn->c; rn->c = getc(rn->f); return 1;
}
static int rn_test2(RN *rn, const char *set) {
  if (rn->c == set[0] || rn->c == set[1]) return rn_next(rn);
  return 0;
}
static int rn_digits(RN *rn, int hex) {
  int n = 0;
  while ((hex ? isxdigit(rn->c) : isdigit(rn->c)) && rn_next(rn)) n++;
  return n;
}
static int read_number(State *L, FILE *f) {
  RN rn; int count = 0, hex = 0;
  rn.f = f; rn.n = 0;
  do { rn.c = getc(f); } while (isspace(rn.c));
  rn_test2(&rn, "-+");
  if (rn_test2(&rn, "00")) { if (rn_test2(&rn, "xX")) hex = 1; else count = 1; }
  count += rn_digits(&rn, hex);
  if (rn_test2(&rn, "..")) count += rn_digits(&rn, hex);
  if (count > 0 && rn_test2(&rn, hex ? "pP" : "eE")) { rn_test2(&rn, "-+"); rn_digits(&rn, 0); }
  ungetc(rn.c, f);
  rn.buff[rn.n] = 0;
  Value v;
  if (rn.n > 0 && str2number(rn.buff, (size_t)rn.n, &v)) { L->ret[0] = v; return 1; }
  return 0;
}
/* reads according to formats a[first..n); results in L->ret; returns count */
static int g_read(State *L, FILE *f, Value *a, int n, int first) {
  int nargs = n - first, nres = 0, success = 1;
  clearerr(f);
  Value *res = alloca(((size_t)(nargs > 0 ? nargs : 1) + 2) * sizeof(Value));
  if (nargs <= 0) {
    LBuf b; lbuf_init(&b);
    success = read_line(f, &b, 1);
    if (success) res[nres++] = lbuf_finish(&b); else { lbuf_free(&b); res[nres++] = NILV; }
  } else {
    for (int i = first; i < n && success; i++) {
      Value fmt = a[i];
      if (fmt.t == T_INT || fmt.t == T_FLT) {
        lint cnt = arg_int(L, a, n, i);
        if (cnt == 0) { int c = getc(f); ungetc(c, f); success = c != EOF; res[nres++] = success ? mkstr(str_new("", 0)) : NILV; }
        else {
          char *buf = malloc((size_t)cnt); size_t r = fread(buf, 1, (size_t)cnt, f);
          success = r > 0; res[nres++] = success ? mkstr(str_new(buf, r)) : NILV; free(buf);
        }
      } else {
        Str *s = arg_str(L, a, n, i); const char *p = s->data;
        if (*p == '*') p++;
        switch (*p) {
          case 'n': success = read_number(L, f); res[nres++] = success ? L->ret[0] : NILV; break;
          case 'l': case 'L': { LBuf b; lbuf_init(&b); success = read_line(f, &b, *p == 'l');
            if (success) res[nres++] = lbuf_finish(&b); else { lbuf_free(&b); res[nres++] = NILV; } break; }
          case 'a': { LBuf b; lbuf_init(&b); char tmp[4096]; size_t r;
            while ((r = fread(tmp, 1, sizeof tmp, f)) > 0) lbuf_add(&b, tmp, r);
            res[nres++] = lbuf_finish(&b); success = 1; break; }
          default: arg_error(L, i - (first ? 1 : 0), "invalid format");
        }
      }
    }
  }
  if (ferror(f)) return fileresult(L, 0, NULL);
  ret_need(L, nres + 1);
  memcpy(L->ret, res, (size_t)nres * sizeof(Value));
  return nres;
}
static int g_write(State *L, FILE *f, Value fv, Value *a, int n, int first) {
  int ok = 1;
  for (int i = first; i < n && ok; i++) {
    if (a[i].t == T_STR) ok = fwrite(strof(a[i])->data, 1, strof(a[i])->len, f) == strof(a[i])->len;
    else if (isnum(a[i])) { char tmp[64]; int l = fmt_number(tmp, a[i]); ok = fwrite(tmp, 1, (size_t)l, f) == (size_t)l; }
    else { char m[100]; snprintf(m, sizeof m, "string expected, got %s", objtypename(a[i])); arg_error(L, i - first, m); }
  }
  if (ok) return ret1(L, fv);
  return fileresult(L, 0, NULL);
}

/* ---------- lines ---------- */
static int lines_iter(State *L, Value *a, int n) {
  CFn *self = L->ci->cf;
  LFile *lf = vfile(self->up[0]);
  if (!lf || lf->closed) lerror(L, "file is already closed");
  int nf = (int)self->up[1].u.i;
  Value *fm = alloca(((size_t)nf + 1) * sizeof(Value));
  for (int i = 0; i < nf; i++) fm[i] = self->up[3 + i];
  int r = g_read(L, lf->f, fm, nf, 0);
  if (r > 0 && truthy(L->ret[0])) return r;
  if (r > 1 && isnil(L->ret[0]) && L->ret[1].t == T_STR) lua_throw(L, L->ret[1]);
  if (truthy(self->up[2])) close_file(L, lf);
  return 0;
}
static CFn *make_lines(State *L, Value file, Value *fmts, int nf, int toclose) {
  if (nf > 250) arg_error(L, 251, "too many arguments");
  CFn *c = cfn_new(lines_iter, "lines_iter", 3 + nf);
  c->up[0] = file; c->up[1] = mkint(nf); c->up[2] = mkbool(toclose);
  for (int i = 0; i < nf; i++) c->up[3 + i] = fmts[i];
  return c;
}
static int f_lines(State *L, Value *a, int n) {
  tofile_open(L, a, n, 0);
  return ret1(L, mkobj(T_CFN, make_lines(L, a[0], a + 1, n - 1, 0)));
}
static int io_lines(State *L, Value *a, int n) {
  if (n < 1 || isnil(a[0])) {
    LFile *lf = vfile(defin); if (lf->closed) lerror(L, "default input file is closed");
    return ret1(L, mkobj(T_CFN, make_lines(L, defin, a + 1 < a + n ? a + 1 : a, n > 1 ? n - 1 : 0, 0)));
  }
  const char *fname = arg_str(L, a, n, 0)->data;
  FILE *f = fopen(fname, "r");
  if (!f) lerror(L, "%s: %s", fname, strerror(errno));
  Value file = new_file(f, 0);
  L->ret[0] = mkobj(T_CFN, make_lines(L, file, a + 1, n - 1, 1));
  L->ret[1] = NILV; L->ret[2] = NILV; L->ret[3] = file;
  return 4;
}

/* ---------- io.* ---------- */
static int io_open(State *L, Value *a, int n) {
  const char *fname = arg_str(L, a, n, 0)->data;
  const char *mode = n >= 2 && !isnil(a[1]) ? arg_str(L, a, n, 1)->data : "r";
  const char *m = mode;
  int ok = *m && strchr("rwa", *m); if (ok) { m++; if (*m == '+') m++; while (*m == 'b') m++; ok = *m == 0; }
  if (!ok) arg_error(L, 1, "invalid mode");
  errno = 0;
  FILE *f = fopen(fname, mode);
  if (!f) return fileresult(L, 0, fname);
  return ret1(L, new_file(f, 0));
}
static int f_close(State *L, Value *a, int n) {
  LFile *lf = tofile_open(L, a, n, 0);
  return close_file(L, lf);
}
static int io_close(State *L, Value *a, int n) {
  if (n < 1) { LFile *lf = vfile(defout); if (lf->closed) lerror(L, "attempt to use a closed file"); return close_file(L, lf); }
  return f_close(L, a, n);
}
static int f_gc(State *L, Value *a, int n) {
  if (n >= 1 && is_file(a[0])) { LFile *lf = vfile(a[0]); if (lf && !lf->closed && lf->kind != 1) close_file(L, lf); }
  return 0;
}
static int f_tostring(State *L, Value *a, int n) {
  if (!(n >= 1 && is_file(a[0]))) arg_typeerror(L, 0, "FILE*", a, n);
  LFile *lf = vfile(a[0]);
  if (!lf || lf->closed) return ret1(L, mkstr(str_newz("file (closed)")));
  return ret1(L, mkstr(str_fmt("file (%p)", (void *)lf->f)));
}
static int io_type(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  if (!is_file(a[0])) return ret1(L, NILV);
  LFile *lf = vfile(a[0]);
  return ret1(L, mkstr(str_newz(!lf || lf->closed ? "closed file" : "file")));
}
static int io_read(State *L, Value *a, int n) {
  LFile *lf = vfile(defin); if (lf->closed) lerror(L, "default input file is closed");
  return g_read(L, lf->f, a, n, 0);
}
static int f_read(State *L, Value *a, int n) { LFile *lf = tofile_open(L, a, n, 0); return g_read(L, lf->f, a, n, 1); }
static int io_write(State *L, Value *a, int n) {
  LFile *lf = vfile(defout); if (lf->closed) lerror(L, "default output file is closed");
  return g_write(L, lf->f, defout, a, n, 0);
}
static int f_write(State *L, Value *a, int n) { LFile *lf = tofile_open(L, a, n, 0); return g_write(L, lf->f, a[0], a, n, 1); }
static int f_flush(State *L, Value *a, int n) {
  LFile *lf = tofile_open(L, a, n, 0);
  if (fflush(lf->f) != 0) return fileresult(L, 0, NULL);
  return ret1(L, a[0]);
}
static int io_flush(State *L, Value *a, int n) {
  LFile *lf = vfile(defout); if (lf->closed) lerror(L, "default output file is closed");
  if (fflush(lf->f) != 0) return fileresult(L, 0, NULL);
  return ret1(L, defout);
}
static int f_seek(State *L, Value *a, int n) {
  LFile *lf = tofile_open(L, a, n, 0);
  const char *w = n >= 2 && !isnil(a[1]) ? arg_str(L, a, n, 1)->data : "cur";
  int wh;
  if (!strcmp(w, "set")) wh = SEEK_SET; else if (!strcmp(w, "cur")) wh = SEEK_CUR; else if (!strcmp(w, "end")) wh = SEEK_END;
  else { char m[80]; snprintf(m, sizeof m, "invalid option '%s'", w); arg_error(L, 1, m); }
  lint off = arg_optint(L, a, n, 2, 0);
  if (fseek(lf->f, (long)off, wh) != 0) return fileresult(L, 0, NULL);
  return ret1(L, mkint((lint)ftell(lf->f)));
}
static int f_setvbuf(State *L, Value *a, int n) {
  LFile *lf = tofile_open(L, a, n, 0);
  const char *m = arg_str(L, a, n, 1)->data;
  int mode;
  if (!strcmp(m, "no")) mode = _IONBF; else if (!strcmp(m, "full")) mode = _IOFBF; else if (!strcmp(m, "line")) mode = _IOLBF;
  else { char b[80]; snprintf(b, sizeof b, "invalid option '%s'", m); arg_error(L, 1, b); }
  lint sz = arg_optint(L, a, n, 2, BUFSIZ);
  return fileresult(L, setvbuf(lf->f, NULL, mode, (size_t)sz) == 0, NULL);
}
static int g_iofile(State *L, Value *a, int n, Value *slot, const char *mode) {
  if (n >= 1 && !isnil(a[0])) {
    if (a[0].t == T_STR) {
      FILE *f = fopen(strof(a[0])->data, mode);
      if (!f) lerror(L, "cannot open file '%s' (%s)", strof(a[0])->data, strerror(errno));
      *slot = new_file(f, 0);
    } else { tofile_open(L, a, n, 0); *slot = a[0]; }
  }
  return ret1(L, *slot);
}
static int io_input(State *L, Value *a, int n) { return g_iofile(L, a, n, &defin, "r"); }
static int io_output(State *L, Value *a, int n) { return g_iofile(L, a, n, &defout, "w"); }
static int io_tmpfile(State *L, Value *a, int n) {
  FILE *f = tmpfile();
  if (!f) return fileresult(L, 0, NULL);
  return ret1(L, new_file(f, 0));
}
static int io_popen(State *L, Value *a, int n) {
  const char *prog = arg_str(L, a, n, 0)->data;
  const char *mode = n >= 2 && !isnil(a[1]) ? arg_str(L, a, n, 1)->data : "r";
  if (!((mode[0] == 'r' || mode[0] == 'w') && mode[1] == 0)) arg_error(L, 1, "invalid mode");
  fflush(NULL);
  errno = 0;
  FILE *f = popen(prog, mode);
  if (!f) return fileresult(L, 0, prog);
  return ret1(L, new_file(f, 2));
}

void open_io(State *L) {
  gc_addroot(&v_meta); gc_addroot(&v_methods); gc_addroot(&defin); gc_addroot(&defout);
  file_meta = tab_new(0, 8); file_methods = tab_new(0, 8);
  v_meta = mktab(file_meta); v_methods = mktab(file_methods);
  reg_func(file_methods, "close", f_close); reg_func(file_methods, "flush", f_flush); reg_func(file_methods, "lines", f_lines);
  reg_func(file_methods, "read", f_read); reg_func(file_methods, "seek", f_seek); reg_func(file_methods, "setvbuf", f_setvbuf);
  reg_func(file_methods, "write", f_write);
  tab_setstr(L, file_meta, str_newz("__index"), v_methods);
  tab_setstr(L, file_meta, str_newz("__name"), mkstr(str_newz("FILE*")));
  reg_func(file_meta, "__tostring", f_tostring); reg_func(file_meta, "__gc", f_gc); reg_func(file_meta, "__close", f_gc);
  Table *t = reg_lib(L, "io");
  reg_func(t, "close", io_close); reg_func(t, "flush", io_flush); reg_func(t, "input", io_input); reg_func(t, "lines", io_lines);
  reg_func(t, "open", io_open); reg_func(t, "output", io_output); reg_func(t, "popen", io_popen); reg_func(t, "read", io_read);
  reg_func(t, "tmpfile", io_tmpfile); reg_func(t, "type", io_type); reg_func(t, "write", io_write);
  Value in = new_file(stdin, 1), out = new_file(stdout, 1), er = new_file(stderr, 1);
  defin = in; defout = out;
  tab_setstr(L, t, str_newz("stdin"), in); tab_setstr(L, t, str_newz("stdout"), out); tab_setstr(L, t, str_newz("stderr"), er);
}
