/* Coroutines: each coroutine runs on its own mmap'd C stack; switching is a tiny assembly routine (x86-64). */
#include "lua.h"
#include <alloca.h>

void co_switch(void **save_sp, void *to_sp);
__asm__(
  ".text\n.globl co_switch\n.type co_switch,@function\nco_switch:\n"
  "  pushq %rbp\n  pushq %rbx\n  pushq %r12\n  pushq %r13\n  pushq %r14\n  pushq %r15\n"
  "  movq %rsp, (%rdi)\n  movq %rsi, %rsp\n"
  "  popq %r15\n  popq %r14\n  popq %r13\n  popq %r12\n  popq %rbx\n  popq %rbp\n  ret\n"
  ".size co_switch,.-co_switch\n");

static void co_boot(void) {
  State *co = G.curL;
  ErrJmp ej; memset(&ej, 0, sizeof ej);
  ej.handler = NILV; ej.ci = NULL;
  co->ej = &ej;
  int n = co->nxfer;
  Value *args = alloca(((size_t)n + 1) * sizeof(Value));
  memcpy(args, co->ret, (size_t)n * sizeof(Value));
  if (setjmp(ej.jb) == 0) {
    int r = call_value(co, co->fn, args, n);
    co->nxfer = r; co->cohaserr = 0;
  } else {
    co->cohaserr = 1; co->errv = ej.err; co->nxfer = 0;
  }
  co->ej = NULL; co->ci = NULL; co->depth = 0;
  co->costatus = CO_DEAD;
  State *res = co->resumer;
  co_switch((void **)&co->sp_saved, res->sp_saved);
  abort();
}

static int co_prepare(State *co) {
  if (!state_alloc_stack(co)) return 0;
  void **sp = (void **)((uintptr_t)co->stack_hi & ~(uintptr_t)15);
  *--sp = NULL;
  *--sp = (void *)co_boot;
  for (int i = 0; i < 6; i++) *--sp = NULL;
  co->sp_saved = (char *)sp;
  return 1;
}

/* returns 0 ok (values in co->ret[0..co->nxfer)), 1 coroutine raised an error (co->errv), 2 cannot resume (*msg) */
static int do_resume(State *L, State *co, Value *args, int n, Value *msg) {
  if (co->costatus == CO_DEAD) { *msg = mkstr(str_newz("cannot resume dead coroutine")); return 2; }
  if (co->costatus != CO_SUSPENDED) { *msg = mkstr(str_newz("cannot resume non-suspended coroutine")); return 2; }
  if (L->depth >= L->maxdepth - 10) { *msg = mkstr(str_newz("C stack overflow")); return 2; }
  if (!co->started) {
    if (!co_prepare(co)) { *msg = mkstr(str_newz("not enough memory")); return 2; }
    co->started = 1;
  }
  ret_need(co, n + 1);
  memcpy(co->ret, args, (size_t)n * sizeof(Value));
  co->nxfer = n;
  co->resumer = L; L->costatus = CO_NORMAL; co->costatus = CO_RUNNING; G.curL = co;
  co_switch((void **)&L->sp_saved, co->sp_saved);
  G.curL = L; L->costatus = CO_RUNNING; co->resumer = NULL;
  if (co->costatus == CO_DEAD) {
    state_release_stack(co); co->sp_saved = NULL;
    if (co->cohaserr) return 1;
  }
  return 0;
}

static State *check_co(State *L, Value *a, int n, int i) {
  if (i < n && a[i].t == T_THREAD) return (State *)a[i].u.p;
  arg_typeerror(L, i, "coroutine", a, n);
}

static int c_create(State *L, Value *a, int n) {
  if (n < 1 || (a[0].t != T_LCL && a[0].t != T_CFN)) arg_typeerror(L, 0, "function", a, n);
  State *co = state_new();
  co->costatus = CO_SUSPENDED; co->fn = a[0];
  return ret1(L, mkobj(T_THREAD, co));
}

static int copy_results(State *L, State *co, int off) {
  int m = co->nxfer;
  ret_need(L, m + off + 1);
  memcpy(L->ret + off, co->ret, (size_t)m * sizeof(Value));
  return m + off;
}

static int c_resume(State *L, Value *a, int n) {
  State *co = check_co(L, a, n, 0);
  Value msg = NILV;
  int r = do_resume(L, co, a + 1, n - 1, &msg);
  if (r == 0) { int m = co->nxfer; ret_need(L, m + 2); memmove(L->ret + 1, co->ret, (size_t)m * sizeof(Value)); L->ret[0] = mkbool(1); return m + 1; }
  Value e = r == 1 ? co->errv : msg;
  L->ret[0] = mkbool(0); L->ret[1] = e; return 2;
}

static int c_yield(State *L, Value *a, int n) {
  if (L->is_main) lerror(L, "attempt to yield from outside a coroutine");
  ret_need(L, n + 1);
  memmove(L->ret, a, (size_t)n * sizeof(Value));
  L->nxfer = n;
  L->costatus = CO_SUSPENDED;
  State *res = L->resumer;
  co_switch((void **)&L->sp_saved, res->sp_saved);
  return L->nxfer;
}

static int c_status(State *L, Value *a, int n) {
  State *co = check_co(L, a, n, 0);
  const char *s;
  if (co == L) s = "running";
  else switch (co->costatus) {
    case CO_SUSPENDED: s = "suspended"; break;
    case CO_NORMAL: s = "normal"; break;
    case CO_RUNNING: s = "running"; break;
    default: s = "dead";
  }
  return ret1(L, mkstr(str_newz(s)));
}
static int c_isyieldable(State *L, Value *a, int n) { return ret1(L, mkbool(!L->is_main)); }
static int c_running(State *L, Value *a, int n) {
  L->ret[0] = mkobj(T_THREAD, L); L->ret[1] = mkbool(L->is_main); return 2;
}

/* protected call helper; returns 1 on success, 0 with *err on error */
static int pcall_simple(State *L, Value fn, Value *args, int n, Value *err) {
  ErrJmp ej; memset(&ej, 0, sizeof ej);
  ej.prev = L->ej; ej.handler = NILV; ej.ci = L->ci; ej.depth = L->depth; ej.ntbc = L->ntbc;
  L->ej = &ej;
  if (setjmp(ej.jb) == 0) { call_value(L, fn, args, n); L->ej = ej.prev; return 1; }
  L->ej = ej.prev; L->ci = ej.ci; L->depth = ej.depth;
  *err = ej.err; return 0;
}

/* close a suspended or dead coroutine: run pending to-be-closed variables. returns 1 if no error */
static int close_co(State *L, State *co, Value *err) {
  int haserr = co->costatus == CO_DEAD && co->cohaserr;
  Value e = haserr ? co->errv : NILV;
  while (co->ntbc > 0) {
    Value v = co->tbc[--co->ntbc];
    Value tm = get_tm(v, TM_CLOSE);
    if (isnil(tm)) continue;
    Value args[2] = {v, e}, ne;
    if (!pcall_simple(L, tm, args, haserr ? 2 : 1, &ne)) { e = ne; haserr = 1; }
  }
  co->costatus = CO_DEAD; co->cohaserr = 0; co->errv = NILV;
  if (co->cstack) { state_release_stack(co); co->sp_saved = NULL; }
  *err = e;
  return !haserr;
}

static int c_close(State *L, Value *a, int n) {
  State *co = check_co(L, a, n, 0);
  if (co == L || co->costatus == CO_RUNNING) lerror(L, "cannot close a running coroutine");
  if (co->costatus == CO_NORMAL) lerror(L, "cannot close a normal coroutine");
  Value e;
  if (close_co(L, co, &e)) return ret1(L, mkbool(1));
  L->ret[0] = mkbool(0); L->ret[1] = e; return 2;
}

static int wrap_call(State *L, Value *a, int n) {
  State *co = (State *)L->ci->cf->up[0].u.p;
  Value msg = NILV;
  int r = do_resume(L, co, a, n, &msg);
  if (r == 0) return copy_results(L, co, 0);
  Value e = r == 1 ? co->errv : msg;
  if (r == 1) { Value ce; if (!close_co(L, co, &ce)) e = ce; }
  if (e.t == T_STR) {
    Str *w = where_str(L, 1);
    if (w->len) {
      size_t tl = w->len + strof(e)->len; char *tmp = malloc(tl + 1);
      memcpy(tmp, w->data, w->len); memcpy(tmp + w->len, strof(e)->data, strof(e)->len);
      e = mkstr(str_new(tmp, tl)); free(tmp);
    }
  }
  lua_throw(L, e);
}
static int c_wrap(State *L, Value *a, int n) {
  c_create(L, a, n);
  Value co = L->ret[0];
  CFn *c = cfn_new(wrap_call, "wrap", 1);
  c->up[0] = co;
  return ret1(L, mkobj(T_CFN, c));
}

void open_coroutine(State *L) {
  (void)L;
  Table *t = reg_lib(L, "coroutine");
  reg_func(t, "create", c_create); reg_func(t, "resume", c_resume); reg_func(t, "yield", c_yield);
  reg_func(t, "status", c_status); reg_func(t, "wrap", c_wrap); reg_func(t, "isyieldable", c_isyieldable);
  reg_func(t, "running", c_running); reg_func(t, "close", c_close);
}
