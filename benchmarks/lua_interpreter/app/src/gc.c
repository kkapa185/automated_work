/* Memory management: object allocation, string interning, mark & sweep GC with
 * conservative scanning of C stacks (exact marking of heap objects). */
#include "lua.h"
#include <stdarg.h>
#include <sys/mman.h>
#include <ucontext.h>

Global G;

static GCObj **gray; static size_t ngray, capgray;

static void oom(void) { fputs("lua: not enough memory\n", stderr); exit(1); }

void gc_init(void) {
  memset(&G, 0, sizeof G);
  G.threshold = 8u << 20;
  G.strsize = 1024; G.strtab = calloc(G.strsize, sizeof(Str *));
  G.seed = 0x9e3779b97f4a7c15ULL;
}

void gc_account(long delta) { G.bytes += delta; }

void *gc_alloc(size_t sz, int type) {
  GCObj *o = malloc(sz);
  if (!o) oom();
  o->gct = (uint8_t)type; o->mark = 0; o->gcnext = G.allgc; G.allgc = o; G.bytes += sz;
  return o;
}

void gc_addroot(Value *v) { if (G.nroots < 64) G.roots[G.nroots++] = v; }
void gc_fix(void *obj) { if (G.nfixed < 256) G.fixed[G.nfixed++] = obj; }

/* ---------- strings ---------- */
static uint32_t hash_bytes(const char *s, size_t l) {
  uint32_t h = 0x811c9dc5u ^ (uint32_t)l;
  for (size_t i = 0; i < l; i++) { h ^= (uint8_t)s[i]; h *= 16777619u; h ^= h >> 15; }
  return h;
}
static size_t str_size(size_t len) { return offsetof(Str, data) + len + 1; }

static void strtab_resize(size_t ns) {
  Str **nt = calloc(ns, sizeof(Str *));
  if (!nt) oom();
  for (size_t i = 0; i < G.strsize; i++) {
    Str *s = G.strtab[i];
    while (s) { Str *nx = s->hnext; size_t b = s->hash & (ns - 1); s->hnext = nt[b]; nt[b] = s; s = nx; }
  }
  free(G.strtab); G.strtab = nt; G.strsize = ns;
}

Str *str_new(const char *s, size_t len) {
  if (len <= 40) {
    uint32_t h = hash_bytes(s, len);
    for (Str *p = G.strtab[h & (G.strsize - 1)]; p; p = p->hnext)
      if (p->hash == h && p->len == len && memcmp(p->data, s, len) == 0) return p;
    if (G.strcount >= G.strsize) strtab_resize(G.strsize * 2);
    Str *n = gc_alloc(str_size(len), T_STR);
    n->isshort = 1; n->hashed = 1; n->hash = h; n->len = len;
    memcpy(n->data, s, len); n->data[len] = 0;
    size_t b = h & (G.strsize - 1); n->hnext = G.strtab[b]; G.strtab[b] = n; G.strcount++;
    return n;
  }
  Str *n = gc_alloc(str_size(len), T_STR);
  n->isshort = 0; n->hashed = 0; n->hash = 0; n->len = len; n->hnext = NULL;
  if (len) memcpy(n->data, s, len);
  n->data[len] = 0;
  return n;
}
Str *str_new_uninit(size_t len) { /* only for len > 40: caller fills data */
  Str *n = gc_alloc(str_size(len), T_STR);
  n->isshort = 0; n->hashed = 0; n->hash = 0; n->len = len; n->hnext = NULL; n->data[len] = 0;
  return n;
}
Str *str_newz(const char *s) { return str_new(s, strlen(s)); }
Str *str_fmt(const char *fmt, ...) {
  char buf[512]; va_list ap; va_start(ap, fmt);
  int n = vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap);
  if (n < (int)sizeof buf) return str_new(buf, n < 0 ? 0 : (size_t)n);
  char *big = malloc((size_t)n + 1); if (!big) oom();
  va_start(ap, fmt); vsnprintf(big, (size_t)n + 1, fmt, ap); va_end(ap);
  Str *r = str_new(big, (size_t)n); free(big); return r;
}
uint32_t str_hash(Str *s) {
  if (!s->hashed) { s->hash = hash_bytes(s->data, s->len); s->hashed = 1; }
  return s->hash;
}
int str_eq(Str *a, Str *b) {
  if (a == b) return 1;
  if (a->isshort || b->isshort) return 0;
  return a->len == b->len && memcmp(a->data, b->data, a->len) == 0;
}
int str_cmp(Str *a, Str *b) {
  size_t m = a->len < b->len ? a->len : b->len;
  int c = memcmp(a->data, b->data, m);
  if (c) return c;
  return a->len < b->len ? -1 : (a->len > b->len);
}

/* ---------- other objects ---------- */
Box *box_new(Value v) { Box *b = gc_alloc(sizeof(Box), T_BOX); b->v = v; return b; }
static size_t cl_size(int nup) { return sizeof(Closure) + (size_t)nup * sizeof(Box *); }
Closure *closure_new(Proto *p, int nup) {
  Closure *c = gc_alloc(cl_size(nup), T_LCL); c->p = p; c->nup = nup;
  for (int i = 0; i < nup; i++) c->upv[i] = NULL;
  return c;
}
static size_t cf_size(int nup) { return sizeof(CFn) + (size_t)nup * sizeof(Value); }
CFn *cfn_new(CFunc fn, const char *name, int nup) {
  CFn *c = gc_alloc(cf_size(nup), T_CFN); c->fn = fn; c->name = name; c->nup = nup;
  for (int i = 0; i < nup; i++) c->up[i] = NILV;
  return c;
}
Udata *udata_new(void) {
  Udata *u = gc_alloc(sizeof(Udata), T_UDATA);
  u->meta = NULL; u->data = NULL; u->fin = NULL; u->uv = NILV; return u;
}
Chunk *chunk_new(void) {
  Chunk *c = gc_alloc(sizeof(Chunk), T_CHUNK);
  c->blocks = NULL; c->consts = NULL; c->nconsts = c->capconsts = 0; c->short_src[0] = 0; c->source = NULL;
  return c;
}
void *arena_alloc(Chunk *c, size_t sz) {
  sz = (sz + 15) & ~(size_t)15;
  ArenaBlk *b = c->blocks;
  if (!b || b->used + sz > b->cap) {
    size_t hdr = (sizeof(ArenaBlk) + 15) & ~(size_t)15;
    size_t cap = sz + hdr > 32768 ? sz + hdr : 32768;
    ArenaBlk *nb = malloc(cap); if (!nb) oom();
    nb->next = c->blocks; nb->used = hdr; nb->cap = cap;
    c->blocks = nb; b = nb; G.bytes += cap;
  }
  void *p = (char *)b + b->used; b->used += sz;
  memset(p, 0, sz);
  return p;
}
void chunk_addconst(Chunk *c, Str *s) {
  if (c->nconsts == c->capconsts) {
    c->capconsts = c->capconsts ? c->capconsts * 2 : 16;
    c->consts = realloc(c->consts, (size_t)c->capconsts * sizeof(Str *));
    if (!c->consts) oom();
  }
  c->consts[c->nconsts++] = s;
}

/* ---------- coroutine stacks pool ---------- */
#define CO_STACK_BIG ((size_t)8 << 20)
#define CO_STACK_SMALL ((size_t)1 << 20)
static void *stack_pool[32]; static int npool;
static void *stack_get(size_t *size) {
  if (npool) { *size = CO_STACK_BIG; return stack_pool[--npool]; }
  size_t sz = CO_STACK_BIG;
  for (;;) {
    void *p = mmap(NULL, sz, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE | MAP_STACK, -1, 0);
    if (p != MAP_FAILED) { *size = sz; return p; }
    if (sz == CO_STACK_SMALL) return NULL;
    sz = CO_STACK_SMALL;
  }
}
static void stack_put(void *p, size_t size) {
  if (size == CO_STACK_BIG && npool < 32) stack_pool[npool++] = p; else munmap(p, size);
}

State *state_new(void) {
  State *L = gc_alloc(sizeof(State), T_THREAD);
  memset((char *)L + sizeof(GCObj), 0, sizeof(State) - sizeof(GCObj));
  L->retcap = 64; L->ret = calloc(64, sizeof(Value));
  L->tailcap = 64; L->tail = calloc(64, sizeof(Value));
  L->tbccap = 0; L->tbc = NULL;
  if (!L->ret || !L->tail) oom();
  L->maxdepth = 200000;
  G.bytes += 64 * 2 * sizeof(Value);
  return L;
}
/* allocate the C stack for a coroutine; returns 0 on failure */
int state_alloc_stack(State *L) {
  size_t sz; void *p = stack_get(&sz);
  if (!p) return 0;
  L->cstack = p; L->cstack_size = sz;
  L->stack_hi = (char *)p + sz;
  L->stack_lo = (char *)p + 40 * 1024;
  return 1;
}
void state_release_stack(State *L) {
  if (L->cstack) { stack_put(L->cstack, L->cstack_size); L->cstack = NULL; }
}

static void state_free(State *L) {
  free(L->ret); free(L->tail); free(L->tbc);
  if (L->cstack) stack_put(L->cstack, L->cstack_size);
}

/* ---------- marking ---------- */
static void gray_push(GCObj *o) {
  if (ngray == capgray) {
    capgray = capgray ? capgray * 2 : 4096;
    gray = realloc(gray, capgray * sizeof(GCObj *)); if (!gray) oom();
  }
  gray[ngray++] = o;
}
static inline void mark_obj(GCObj *o) {
  if (o->mark) return;
  o->mark = 1;
  if (o->gct != T_STR) gray_push(o);
}
static inline void mark_val(Value v) { if (v.t >= T_STR) mark_obj((GCObj *)v.u.p); }

static uintptr_t *aset; static size_t acap_; static uintptr_t amin, amax;
static inline size_t ahash(uintptr_t a) { return (size_t)((a >> 4) * 0x9e3779b97f4a7c15ULL >> 20); }
static void aset_build(void) {
  size_t n = 0;
  for (GCObj *o = G.allgc; o; o = o->gcnext) n++;
  size_t cap = 16; while (cap < n * 2) cap <<= 1;
  free(aset); aset = calloc(cap, sizeof(uintptr_t)); if (!aset) oom();
  acap_ = cap; amin = (uintptr_t)-1; amax = 0;
  for (GCObj *o = G.allgc; o; o = o->gcnext) {
    uintptr_t a = (uintptr_t)o;
    if (a < amin) amin = a;
    if (a > amax) amax = a;
    size_t h = ahash(a) & (cap - 1);
    while (aset[h]) h = (h + 1) & (cap - 1);
    aset[h] = a;
  }
}
static void scan_range(void *lo, void *hi) {
  uintptr_t *p = (uintptr_t *)(((uintptr_t)lo + 7) & ~(uintptr_t)7);
  uintptr_t *e = (uintptr_t *)((uintptr_t)hi & ~(uintptr_t)7);
  size_t mask = acap_ - 1;
  for (; p < e; p++) {
    uintptr_t w = *p;
    if (w < amin || w > amax || (w & 7)) continue;
    size_t h = ahash(w) & mask;
    while (aset[h]) { if (aset[h] == w) { mark_obj((GCObj *)w); break; } h = (h + 1) & mask; }
  }
}

static void mark_table(Table *t) {
  if (t->meta) mark_obj((GCObj *)t->meta);
  for (uint32_t i = 0; i < t->asize; i++) mark_val(t->arr[i]);
  for (uint32_t i = 0; i < t->hcap; i++) {
    if (t->node[i].k.t != T_NIL) { mark_val(t->node[i].k); mark_val(t->node[i].v); }
  }
}
static void mark_thread(State *L) {
  /* L->ret and L->tail only hold values in flight between a call and its consumer; collections happen only at
   * safe points (function entry, loop back edges) where nothing is in flight, so they are not roots. Scanning
   * them would keep stale results (e.g. the table returned by `pairs`) alive. */
  for (int i = 0; i < L->ntbc; i++) mark_val(L->tbc[i]);
  mark_val(L->tailfn); mark_val(L->fn); mark_val(L->errv);
  if (L->resumer) mark_obj((GCObj *)L->resumer);
  scan_range(L, (char *)L + sizeof(State));
  if (L != G.curL && L->costatus != CO_DEAD && (L->is_main || L->cstack) && L->sp_saved) scan_range(L->sp_saved, L->stack_hi);
}
static void propagate(void) {
  while (ngray) {
    GCObj *o = gray[--ngray];
    switch (o->gct) {
      case T_TABLE: mark_table((Table *)o); break;
      case T_LCL: {
        Closure *c = (Closure *)o;
        mark_obj((GCObj *)c->p->chunk);
        for (int i = 0; i < c->nup; i++) if (c->upv[i]) mark_obj((GCObj *)c->upv[i]);
        break;
      }
      case T_CFN: { CFn *c = (CFn *)o; for (int i = 0; i < c->nup; i++) mark_val(c->up[i]); break; }
      case T_BOX: mark_val(((Box *)o)->v); break;
      case T_UDATA: { Udata *u = (Udata *)o; if (u->meta) mark_obj((GCObj *)u->meta); mark_val(u->uv); break; }
      case T_THREAD: mark_thread((State *)o); break;
      case T_CHUNK: { Chunk *c = (Chunk *)o; for (int i = 0; i < c->nconsts; i++) mark_obj((GCObj *)c->consts[i]); break; }
    }
  }
}

static void free_obj(GCObj *o) {
  switch (o->gct) {
    case T_STR: G.bytes -= str_size(((Str *)o)->len); break;
    case T_TABLE: { Table *t = (Table *)o; G.bytes -= sizeof(Table) + t->acap * sizeof(Value) + t->hcap * sizeof(HNode); tab_free(t); break; }
    case T_LCL: G.bytes -= cl_size(((Closure *)o)->nup); break;
    case T_CFN: G.bytes -= cf_size(((CFn *)o)->nup); break;
    case T_BOX: G.bytes -= sizeof(Box); break;
    case T_UDATA: { Udata *u = (Udata *)o; if (u->fin) u->fin(u); G.bytes -= sizeof(Udata); break; }
    case T_THREAD: state_free((State *)o); G.bytes -= sizeof(State) + 128 * sizeof(Value); break;
    case T_CHUNK: {
      Chunk *c = (Chunk *)o; ArenaBlk *b = c->blocks;
      while (b) { ArenaBlk *nx = b->next; G.bytes -= b->cap; free(b); b = nx; }
      free(c->consts); G.bytes -= sizeof(Chunk); break;
    }
  }
  free(o);
}

static void sweep_strtab(void) {
  for (size_t i = 0; i < G.strsize; i++) {
    Str **pp = &G.strtab[i];
    while (*pp) {
      if ((*pp)->gc.mark) pp = &(*pp)->hnext;
      else { *pp = (*pp)->hnext; G.strcount--; }
    }
  }
}

static void __attribute__((noinline)) do_collect(State *L) {
  ucontext_t uc;
  memset(&uc, 0, sizeof uc);
  getcontext(&uc);                         /* spills all registers onto this stack */
  aset_build();
  ngray = 0;
  mark_obj((GCObj *)G.globals); mark_obj((GCObj *)G.registry);
  if (G.loaded) mark_obj((GCObj *)G.loaded);
  if (G.strmeta) mark_obj((GCObj *)G.strmeta);
  for (int i = 0; i < TM_N; i++) if (G.tmname[i]) mark_obj((GCObj *)G.tmname[i]);
  for (int i = 0; i < G.nroots; i++) mark_val(*G.roots[i]);
  for (int i = 0; i < G.nfixed; i++) mark_obj((GCObj *)G.fixed[i]);
  mark_val(G.msgh);
  if (G.next_fn) mark_obj((GCObj *)G.next_fn);
  if (G.ipairs_iter) mark_obj((GCObj *)G.ipairs_iter);
  mark_obj((GCObj *)G.mainL);
  State *cur = G.curL ? G.curL : L;
  mark_obj((GCObj *)cur);
  if (L != cur) mark_obj((GCObj *)L);
  /* the running thread's stack, from here up */
  scan_range(&uc, cur->stack_hi);
  mark_thread(cur);
  propagate();
  sweep_strtab();
  GCObj **pp = &G.allgc;
  while (*pp) {
    GCObj *o = *pp;
    if (o->mark) { o->mark = 0; pp = &o->gcnext; }
    else { *pp = o->gcnext; free_obj(o); }
  }
  free(aset); aset = NULL;
  G.threshold = G.bytes * 2 < (8u << 20) ? (8u << 20) : G.bytes * 2;
}

void gc_collect(State *L) {
  if (G.gcrunning) return;
  G.gcrunning = 1;
  do_collect(L);
  G.gcrunning = 0;
}
