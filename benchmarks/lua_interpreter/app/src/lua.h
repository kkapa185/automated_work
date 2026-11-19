/* Lua 5.5 interpreter -- shared declarations */
#ifndef LUA_H
#define LUA_H
#define _GNU_SOURCE
#include <stdint.h>
#include <stddef.h>
#include <setjmp.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <ucontext.h>

typedef int64_t lint;
typedef uint64_t luint;
typedef double lnum;

enum { T_NIL, T_BOOL, T_INT, T_FLT, T_STR, T_TABLE, T_LCL, T_CFN, T_THREAD, T_UDATA, T_BOX, T_CHUNK };

typedef struct Value { union { lint i; lnum n; void *p; int b; } u; uint8_t t; } Value;

typedef struct GCObj { struct GCObj *gcnext; uint8_t gct; uint8_t mark; } GCObj;

typedef struct Str {
  GCObj gc; uint8_t isshort; uint8_t hashed; uint32_t hash; size_t len;
  struct Str *hnext; char data[1];
} Str;

typedef struct Node_ { Value k, v; } HNode;
typedef struct Table {
  GCObj gc; uint8_t pad;
  Value *arr; uint32_t asize, acap;
  HNode *node; uint32_t hcap, hused;
  struct Table *meta;
} Table;

typedef struct Box { GCObj gc; Value v; } Box;

struct State; struct Node; struct Block; struct Proto; struct Chunk;
typedef int (*CFunc)(struct State *L, Value *a, int n);

typedef struct CFn { GCObj gc; CFunc fn; const char *name; int nup; Value up[1]; } CFn;

typedef struct Closure { GCObj gc; struct Proto *p; int nup; Box *upv[1]; } Closure;

typedef struct Udata { GCObj gc; Table *meta; void *data; void (*fin)(struct Udata *); Value uv; } Udata;

/* ---------- AST ---------- */
typedef struct VarInfo { Str *name; int slot; uint8_t captured, attr; } VarInfo; /* attr: 0 none,1 const,2 close,3 ctrl-const */
typedef struct Label { Str *name; int line; struct Block *blk; int idx; int nactive; int trailing; } Label;
typedef struct Block { struct Node **stmts; int n; Label **labels; int nlabels; uint8_t hasclose; } Block;
typedef struct UpDesc { uint8_t fromlocal; int idx; Str *name; } UpDesc;
typedef struct Proto {
  int nparams, is_vararg, nslots, nup, line, lastline, hasclose;
  UpDesc *up; VarInfo **params; Block *body; Str *name; struct Chunk *chunk;
} Proto;

typedef struct Node {
  uint8_t k, op, flag; int line; int slot;
  struct Node *a, *b, *c;
  struct Node **list; int n;
  struct Node **list2; int n2;
  Block *blk; Str *name;
  union { lint i; lnum n; Str *s; Proto *p; VarInfo *vi; VarInfo **vars; Label *lbl; } u;
} Node;

typedef struct ArenaBlk { struct ArenaBlk *next; size_t used, cap; } ArenaBlk;
typedef struct Chunk { GCObj gc; ArenaBlk *blocks; Str **consts; int nconsts, capconsts; char short_src[80]; Str *source; } Chunk;

enum { /* expressions */
  E_NIL, E_TRUE, E_FALSE, E_INT, E_FLT, E_STR, E_VARARG, E_LOCAL, E_BOXED, E_UPVAL,
  E_INDEX, E_FIELD, E_CALL, E_METH, E_FUNC, E_BIN, E_AND, E_OR, E_NOT, E_NEG, E_LEN, E_BNOT,
  E_CONCAT, E_TABLE, E_PAREN, E_GLOBAL /* unused placeholder */, IT_POS, IT_KEY,
  /* statements */
  S_LOCAL, S_ASSIGN, S_CALL, S_DO, S_WHILE, S_REPEAT, S_IF, S_FORNUM, S_FORIN, S_LOCALFUNC,
  S_RETURN, S_BREAK, S_GOTO, S_LABEL, S_GLOBAL, S_GLOBALFUNC
};
enum { OP_ADD, OP_SUB, OP_MUL, OP_MOD, OP_POW, OP_DIV, OP_IDIV, OP_BAND, OP_BOR, OP_BXOR, OP_SHL, OP_SHR,
       OP_EQ, OP_NE, OP_LT, OP_LE, OP_GT, OP_GE };

/* ---------- runtime ---------- */
typedef struct CallInfo {
  struct CallInfo *prev; Closure *cl; CFn *cf; int line; Node *callnode; int istail;
} CallInfo;

typedef struct ErrJmp {
  jmp_buf jb; struct ErrJmp *prev; Value handler; Value err; CallInfo *ci; int depth; int ntbc; int inhandler;
} ErrJmp;

typedef struct TbcEntry { Value v; } TbcEntry;

enum { CO_SUSPENDED, CO_RUNNING, CO_NORMAL, CO_DEAD };

typedef struct State {
  GCObj gc;
  Value *ret; int nret, retcap;
  Value *tail; int ntail, tailcap; Value tailfn;
  CallInfo *ci; int depth, maxdepth;
  ErrJmp *ej;
  char *stack_lo, *stack_hi, *sp_saved;
  Node *callnode;
  int badop;
  Value *tbc; int ntbc, tbccap;
  /* coroutine */
  int costatus; int is_main;
  struct State *resumer;
  Value fn; Value *xfer; int nxfer; Value errv; int cohaserr;
  void *cstack; size_t cstack_size;
  ucontext_t ctx; ucontext_t *back;
  int started;
} State;

/* Frame for executing a Lua function */
typedef struct Frame { Value *slots; Closure *cl; Value *varargs; int nvarargs; CallInfo *ci; } Frame;

enum { TM_INDEX, TM_NEWINDEX, TM_GC, TM_MODE, TM_LEN, TM_EQ, TM_ADD, TM_SUB, TM_MUL, TM_MOD, TM_POW, TM_DIV,
       TM_IDIV, TM_BAND, TM_BOR, TM_BXOR, TM_SHL, TM_SHR, TM_UNM, TM_BNOT, TM_LT, TM_LE, TM_CONCAT, TM_CALL,
       TM_CLOSE, TM_TOSTRING, TM_NAME, TM_PAIRS, TM_METATABLE, TM_N };

typedef struct Global {
  GCObj *allgc; size_t bytes, threshold; int gcrunning; int gcstop;
  Str **strtab; size_t strsize, strcount;
  Table *globals, *registry, *loaded; Table *strmeta;
  State *mainL, *curL;
  Str *tmname[TM_N];
  Value *roots[64]; int nroots; void *fixed[256]; int nfixed;
  CFn *next_fn, *ipairs_iter;
  Value msgh;
  uint64_t seed;
} Global;
extern Global G;

#define NILV ((Value){.t = T_NIL})
static inline Value mkint(lint i) { Value v; v.t = T_INT; v.u.i = i; return v; }
static inline Value mkflt(lnum n) { Value v; v.t = T_FLT; v.u.n = n; return v; }
static inline Value mkbool(int b) { Value v; v.t = T_BOOL; v.u.b = b != 0; return v; }
static inline Value mkobj(int t, void *p) { Value v; v.t = (uint8_t)t; v.u.p = p; return v; }
static inline Value mkstr(Str *s) { return mkobj(T_STR, s); }
static inline Value mktab(Table *t) { return mkobj(T_TABLE, t); }
static inline int truthy(Value v) { return v.t > T_BOOL || (v.t == T_BOOL && v.u.b); }
#define isnil(v) ((v).t == T_NIL)
#define isnum(v) ((v).t == T_INT || (v).t == T_FLT)
#define strof(v) ((Str *)(v).u.p)
#define tabof(v) ((Table *)(v).u.p)
#define STRDATA(s) ((s)->data)

/* gc.c */
void gc_init(void);
void *gc_alloc(size_t sz, int type);
void gc_account(long delta);
void gc_collect(State *L);
static inline void gc_check(State *L) { if (G.bytes > G.threshold && !G.gcstop) gc_collect(L); }
void gc_addroot(Value *v);
void gc_fix(void *obj);
Str *str_new(const char *s, size_t len);
Str *str_newz(const char *s);
Str *str_new_uninit(size_t len);
Str *str_fmt(const char *fmt, ...);
uint32_t str_hash(Str *s);
int str_eq(Str *a, Str *b);
int str_cmp(Str *a, Str *b);
Box *box_new(Value v);
Closure *closure_new(Proto *p, int nup);
CFn *cfn_new(CFunc fn, const char *name, int nup);
Udata *udata_new(void);
State *state_new(void);
Chunk *chunk_new(void);
void *arena_alloc(Chunk *c, size_t sz);
void chunk_addconst(Chunk *c, Str *s);
int state_alloc_stack(State *L);
void state_release_stack(State *L);

/* table.c */
Table *tab_new(int narr, int nhash);
Value tab_get(Table *t, Value k);
Value tab_getint(Table *t, lint k);
Value tab_getstr(Table *t, Str *k);
void tab_set(State *L, Table *t, Value k, Value v);
void tab_setint(State *L, Table *t, lint k, Value v);
void tab_setstr(State *L, Table *t, Str *k, Value v);
void tab_ctor_set(State *L, Table *t, lint idx, Value v);
void tab_reserve_arr(Table *t, uint32_t n);
lint tab_len(Table *t);
int tab_next(State *L, Table *t, Value *key, Value *val);
int tab_iter(Table *t, size_t *cursor, Value *k, Value *v);
void tab_free(Table *t);
size_t tab_size(Table *t);
void tab_resize_hash_for(Table *t, uint32_t n);

/* value.c */
const char *typename_of(int t);
const char *objtypename(Value v);
int tonumber_v(Value v, Value *out);              /* number or numeric string */
int tointeger_v(Value v, lint *out);              /* exact conversion, strings ok */
int tointeger_num(Value v, lint *out);            /* numbers only (no strings) */
int dbl2int(double d, lint *out);
int str2number(const char *s, size_t len, Value *out);
int fmt_number(char *buf, Value v);
Value tostring_basic(Value v);
Value tostring_meta(State *L, Value v);
int raw_equal(Value a, Value b);
int val_equal(State *L, Value a, Value b);
int val_lt(State *L, Value a, Value b);
int val_le(State *L, Value a, Value b);
int num_lt(Value a, Value b);
int num_le(Value a, Value b);
Table *getmetatable_of(Value v);
Value get_tm(Value v, int tm);
Value index_val(State *L, Value o, Value k, int *ok);
Value index_str(State *L, Value o, Str *k, int *ok);
int setindex_val(State *L, Value o, Value k, Value v, Value *bad);
int arith_try(State *L, int op, Value a, Value b, Value *res);
Value arith_val(State *L, int op, Value a, Value b);
Value concat_vals(State *L, Value *v, int n);
int concat_try(State *L, Value a, Value b, Value *res);
Value len_val(State *L, Value v, int *ok);
lint shift_left(lint a, lint n);
lint int_idiv(State *L, lint a, lint b);
lint int_mod(State *L, lint a, lint b);
lnum flt_mod(lnum a, lnum b);

/* interp.c */
int call_value(State *L, Value fn, Value *args, int nargs);
int call_lua(State *L, Closure *cl, Value *args, int nargs);
Value call1(State *L, Value fn, Value *args, int n);
int protected_call(State *L, Value fn, Value *args, int n, Value *err); /* -1 on error (value in *err) */
void lua_throw(State *L, Value v) __attribute__((noreturn));
void lerror(State *L, const char *fmt, ...) __attribute__((noreturn, format(printf, 2, 3)));
Str *where_str(State *L, int level);
void ret_need(State *L, int n);
static inline int ret1(State *L, Value v) { L->ret[0] = v; return 1; }
Value make_closure_main(State *L, Proto *p, Value env);
Closure *load_chunk(State *L, const char *src, size_t len, const char *chunkname, Value env, char *mode, Value *errmsg);
Str *traceback_str(State *L, const char *msg, int level);
void tbc_close_to(State *L, int level, Value err, int haserr);
Value tbc_unwind(State *L, int level, Value err);
void interp_init(State *L);
size_t stack_avail(State *L);

/* parse.c */
Proto *parse_chunk(State *L, const char *src, size_t len, const char *chunkname, Value *errmsg);
void chunkid(char *out, size_t outsz, const char *source, size_t srclen);

/* libs */
void open_base(State *L);
void open_string(State *L);
void open_table(State *L);
void open_math(State *L);
void open_os(State *L);
void open_io(State *L);
void open_utf8(State *L);
void open_coroutine(State *L);
void open_package(State *L);
void reg_func(Table *t, const char *name, CFunc f);
void reg_ufunc(Table *t, const char *name, CFunc f, int nup, Value *ups);
Table *reg_lib(State *L, const char *name);
const char *fn_display_name(CFn *c);

/* growable byte buffer used by libraries */
typedef struct LBuf { char *p; size_t n, cap; } LBuf;
void lbuf_init(LBuf *b);
void lbuf_add(LBuf *b, const char *s, size_t l);
void lbuf_addc(LBuf *b, char c);
Value lbuf_finish(LBuf *b);
void lbuf_free(LBuf *b);
Value geti_v(State *L, Value t, lint i);
void seti_v(State *L, Value t, lint i, Value v);

/* argument helpers (a = args, n = count, i = 0-based) */
void arg_error(State *L, int i, const char *msg) __attribute__((noreturn));
void arg_typeerror(State *L, int i, const char *tname, Value *a, int n) __attribute__((noreturn));
lint arg_int(State *L, Value *a, int n, int i);
lint arg_optint(State *L, Value *a, int n, int i, lint def);
lnum arg_num(State *L, Value *a, int n, int i);
lnum arg_optnum(State *L, Value *a, int n, int i, lnum def);
Str *arg_str(State *L, Value *a, int n, int i);
Table *arg_table(State *L, Value *a, int n, int i);
void arg_any(State *L, Value *a, int n, int i);
static inline Value argv(Value *a, int n, int i) { return i < n ? a[i] : NILV; }

#endif
