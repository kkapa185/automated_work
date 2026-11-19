/* Command line driver: ./lua [script [args]] */
#include "lua.h"
#include <sys/mman.h>
#include <ucontext.h>
#include <unistd.h>

static int g_argc; static char **g_argv; static int g_status;
static ucontext_t main_ctx, run_ctx;

static int msgh(State *L, Value *a, int n) {
  Value m = argv(a, n, 0);
  if (m.t != T_STR) {
    Value tm = get_tm(m, TM_TOSTRING);
    if (!isnil(tm) && m.t == T_TABLE) { Value s = tostring_meta(L, m); m = s; }
    else if (isnum(m)) m = tostring_basic(m);
    else return ret1(L, mkstr(str_fmt("(error object is a %s value)", objtypename(m))));
  }
  return ret1(L, mkstr(traceback_str(L, strof(m)->data, 1)));
}

static void report(State *L, Value err) {
  (void)L;
  Value s = err.t == T_STR ? err : tostring_basic(err);
  fflush(stdout);
  fprintf(stderr, "lua: %s\n", strof(s)->data);
  fflush(stderr);
}

static void run_main(void) {
  State *L = G.mainL;
  char **argv = g_argv; int argc = g_argc;
  open_base(L); open_string(L); open_table(L); open_math(L); open_os(L); open_io(L); open_utf8(L);
  open_coroutine(L); open_package(L);
  int i = 1; const char *script = NULL; int nopt_e = 0; const char *ecode = NULL;
  for (; i < argc; i++) {
    if (!strcmp(argv[i], "-e") && i + 1 < argc) { ecode = argv[++i]; nopt_e = 1; }
    else if (!strcmp(argv[i], "-v")) { printf("Lua 5.5\n"); }
    else if (!strcmp(argv[i], "-")) { script = "-"; i++; break; }
    else if (argv[i][0] == '-' && argv[i][1]) { fprintf(stderr, "lua: unrecognized option '%s'\n", argv[i]); g_status = 1; return; }
    else { script = argv[i]; i++; break; }
  }
  /* arg table */
  Table *at = tab_new(argc, 4);
  int sidx = script ? i - 1 : argc;
  for (int k = 0; k < argc; k++) tab_set(L, at, mkint((lint)(k - sidx)), mkstr(str_newz(argv[k])));
  tab_setstr(L, G.globals, str_newz("arg"), mktab(at));
  Value fn = NILV; Value err;
  if (ecode) {
    Closure *c = load_chunk(L, ecode, strlen(ecode), "=(command line)", mktab(G.globals), NULL, &err);
    if (!c) { report(L, err); g_status = 1; return; }
    fn = mkobj(T_LCL, c);
  } else if (script) {
    FILE *fp = strcmp(script, "-") ? fopen(script, "rb") : stdin;
    if (!fp) { fprintf(stderr, "lua: cannot open %s\n", script); g_status = 1; return; }
    size_t cap = 8192, n = 0; char *buf = malloc(cap);
    for (;;) { size_t r = fread(buf + n, 1, cap - n, fp); n += r; if (n < cap) break; cap *= 2; buf = realloc(buf, cap); }
    if (fp != stdin) fclose(fp);
    char cn[1024]; snprintf(cn, sizeof cn, "@%s", strcmp(script, "-") ? script : "stdin");
    Closure *c = load_chunk(L, buf, n, cn, mktab(G.globals), NULL, &err);
    free(buf);
    if (!c) { report(L, err); g_status = 1; return; }
    fn = mkobj(T_LCL, c);
  } else if (nopt_e) return;
  else {
    size_t cap = 8192, n = 0; char *buf = malloc(cap);
    for (;;) { size_t r = fread(buf + n, 1, cap - n, stdin); n += r; if (n < cap) break; cap *= 2; buf = realloc(buf, cap); }
    Closure *c = load_chunk(L, buf, n, "=stdin", mktab(G.globals), NULL, &err);
    free(buf);
    if (!c) { report(L, err); g_status = 1; return; }
    fn = mkobj(T_LCL, c);
  }
  int nargs = 0; Value *args = NULL;
  if (script) { nargs = argc - i; args = alloca(((size_t)nargs + 1) * sizeof(Value)); for (int k = 0; k < nargs; k++) args[k] = mkstr(str_newz(argv[i + k])); }
  ErrJmp ej; memset(&ej, 0, sizeof ej);
  ej.prev = NULL; ej.handler = G.msgh; ej.ci = L->ci; ej.depth = 0;
  L->ej = &ej;
  if (setjmp(ej.jb) == 0) {
    call_value(L, fn, args, nargs);
    L->ej = NULL;
    g_status = 0;
  } else {
    L->ej = NULL;
    report(L, ej.err);
    g_status = 1;
  }
}

static void trampoline(void) { run_main(); }

int main(int argc, char **argv) {
  g_argc = argc; g_argv = argv;
  setvbuf(stderr, NULL, _IONBF, 0);
  gc_init();
  State *L = state_new();
  L->is_main = 1; L->costatus = CO_RUNNING;
  G.mainL = L; G.curL = L;
  G.globals = tab_new(0, 64); G.registry = tab_new(0, 8); G.loaded = tab_new(0, 16);
  interp_init(L);
  G.msgh = mkobj(T_CFN, cfn_new(msgh, "msgh", 0));
  size_t sz = (size_t)1 << 30; void *stk = MAP_FAILED;
  while (sz >= ((size_t)16 << 20)) {
    stk = mmap(NULL, sz, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE | MAP_STACK, -1, 0);
    if (stk != MAP_FAILED) break;
    sz >>= 1;
  }
  if (stk == MAP_FAILED) { fputs("lua: cannot allocate stack\n", stderr); return 1; }
  L->stack_hi = (char *)stk + sz; L->stack_lo = (char *)stk + 256 * 1024;
  L->maxdepth = 200000;
  if ((size_t)(sz / 1100) < (size_t)L->maxdepth) L->maxdepth = (int)(sz / 1100);
  getcontext(&run_ctx);
  run_ctx.uc_stack.ss_sp = stk; run_ctx.uc_stack.ss_size = sz; run_ctx.uc_link = &main_ctx;
  makecontext(&run_ctx, trampoline, 0);
  swapcontext(&main_ctx, &run_ctx);
  fflush(stdout);
  return g_status;
}
