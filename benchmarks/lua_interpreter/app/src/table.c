/* Lua tables: dynamic array part (keys 1..asize) + open-addressing hash part. */
#include "lua.h"

static void oom(void) { fputs("lua: not enough memory\n", stderr); exit(1); }

static inline uint32_t hash_int(lint i) {
  uint64_t x = (uint64_t)i; x ^= x >> 32; x *= 0x9e3779b1u; x ^= x >> 15; return (uint32_t)x;
}
static inline uint32_t hash_ptr(void *p) {
  uint64_t x = (uint64_t)(uintptr_t)p >> 4; x *= 0x9e3779b97f4a7c15ULL; return (uint32_t)(x >> 32);
}
static uint32_t hash_val(Value k) {
  switch (k.t) {
    case T_INT: return hash_int(k.u.i);
    case T_FLT: { uint64_t b; memcpy(&b, &k.u.n, 8); return hash_int((lint)b); }
    case T_BOOL: return (uint32_t)k.u.b + 1;
    case T_STR: return str_hash(strof(k));
    default: return hash_ptr(k.u.p);
  }
}
static inline int key_eq(Value a, Value b) {
  if (a.t != b.t) return 0;
  switch (a.t) {
    case T_INT: return a.u.i == b.u.i;
    case T_FLT: return a.u.n == b.u.n;
    case T_BOOL: return a.u.b == b.u.b;
    case T_STR: return str_eq(strof(a), strof(b));
    default: return a.u.p == b.u.p;
  }
}

Table *tab_new(int narr, int nhash) {
  Table *t = gc_alloc(sizeof(Table), T_TABLE);
  t->arr = NULL; t->asize = t->acap = 0; t->node = NULL; t->hcap = t->hused = 0; t->meta = NULL;
  if (narr > 0) tab_reserve_arr(t, (uint32_t)narr);
  if (nhash > 0) tab_resize_hash_for(t, (uint32_t)nhash);
  return t;
}
void tab_free(Table *t) { free(t->arr); free(t->node); }
size_t tab_size(Table *t) { return sizeof(Table) + t->acap * sizeof(Value) + t->hcap * sizeof(HNode); }

void tab_reserve_arr(Table *t, uint32_t n) {
  if (n <= t->acap) return;
  Value *na = realloc(t->arr, (size_t)n * sizeof(Value));
  if (!na) oom();
  for (uint32_t i = t->acap; i < n; i++) na[i] = NILV;
  gc_account((long)(n - t->acap) * (long)sizeof(Value));
  t->arr = na; t->acap = n;
}

static void hash_alloc(Table *t, uint32_t cap) {
  HNode *nn = malloc((size_t)cap * sizeof(HNode));
  if (!nn) oom();
  for (uint32_t i = 0; i < cap; i++) { nn[i].k = NILV; nn[i].v = NILV; }
  gc_account((long)cap * (long)sizeof(HNode) - (long)t->hcap * (long)sizeof(HNode));
  free(t->node);
  t->node = nn; t->hcap = cap; t->hused = 0;
}

static void migrate(Table *t);
static inline int ceil_log2(uint32_t k) { return k <= 1 ? 0 : 32 - __builtin_clz(k - 1); }

/* Choose the largest n = 2^i such that more than n/2 of the slots 1..n would be in use, counting the integer keys
 * of both parts plus the key being inserted; move hash entries with keys in (asize, n] into the array part. */
static void grow_array_from_hash(Table *t, Value newkey) {
  uint32_t nums[33]; memset(nums, 0, sizeof nums);
  uint32_t total = 0;
  for (uint32_t i = 0; i < t->asize; i++) if (t->arr[i].t != T_NIL) { nums[ceil_log2(i + 1)]++; total++; }
  for (uint32_t i = 0; i < t->hcap; i++) {
    HNode *n = &t->node[i];
    if (n->k.t == T_INT && n->v.t != T_NIL && n->k.u.i >= 1 && n->k.u.i <= 0x40000000) { nums[ceil_log2((uint32_t)n->k.u.i)]++; total++; }
  }
  if (newkey.t == T_INT && newkey.u.i >= 1 && newkey.u.i <= 0x40000000) { nums[ceil_log2((uint32_t)newkey.u.i)]++; total++; }
  uint32_t a = 0, optimal = 0;
  uint64_t twotoi = 1;
  for (int i = 0; i < 31 && total > twotoi / 2; i++, twotoi *= 2) {
    a += nums[i];
    if (a > twotoi / 2) optimal = (uint32_t)twotoi;
  }
  if (optimal <= t->asize) return;
  tab_reserve_arr(t, optimal);
  uint32_t maxk = t->asize;
  for (uint32_t i = 0; i < t->hcap; i++) {
    HNode *n = &t->node[i];
    if (n->k.t == T_INT && n->v.t != T_NIL && n->k.u.i > (lint)t->asize && n->k.u.i <= (lint)optimal) {
      t->arr[n->k.u.i - 1] = n->v; n->v = NILV;
      if ((uint32_t)n->k.u.i > maxk) maxk = (uint32_t)n->k.u.i;
    }
  }
  t->asize = maxk;
}

static void rehash(Table *t, uint32_t extra, Value newkey) {
  if (t->hcap) grow_array_from_hash(t, newkey);
  HNode *old = t->node; uint32_t ocap = t->hcap, nlive = 0;
  for (uint32_t i = 0; i < ocap; i++) if (old[i].k.t != T_NIL && old[i].v.t != T_NIL) nlive++;
  uint32_t cap = 4;
  while (cap < (nlive + extra + 1) * 2) cap <<= 1;
  HNode *nn = malloc((size_t)cap * sizeof(HNode));
  if (!nn) oom();
  for (uint32_t i = 0; i < cap; i++) { nn[i].k = NILV; nn[i].v = NILV; }
  gc_account((long)cap * (long)sizeof(HNode) - (long)ocap * (long)sizeof(HNode));
  t->node = nn; t->hcap = cap; t->hused = 0;
  for (uint32_t i = 0; i < ocap; i++) {
    if (old[i].k.t != T_NIL && old[i].v.t != T_NIL) {
      uint32_t h = hash_val(old[i].k) & (cap - 1);
      while (nn[h].k.t != T_NIL) h = (h + 1) & (cap - 1);
      nn[h] = old[i]; t->hused++;
    }
  }
  free(old);
  if (t->hused) migrate(t);
}
void tab_resize_hash_for(Table *t, uint32_t n) {
  if (t->hcap == 0) { uint32_t cap = 4; while (cap < (n + 1) * 2) cap <<= 1; hash_alloc(t, cap); }
}

static int hfind(Table *t, Value k, uint32_t h) {
  if (!t->hcap) return -1;
  uint32_t mask = t->hcap - 1, i = h & mask;
  for (;;) {
    HNode *n = &t->node[i];
    if (n->k.t == T_NIL) return -1;
    if (key_eq(n->k, k)) return (int)i;
    i = (i + 1) & mask;
  }
}

Value tab_getstr(Table *t, Str *k) {
  if (!t->hcap) return NILV;
  uint32_t mask = t->hcap - 1, i = str_hash(k) & mask;
  for (;;) {
    HNode *n = &t->node[i];
    if (n->k.t == T_NIL) return NILV;
    if (n->k.t == T_STR && (n->k.u.p == k || str_eq(strof(n->k), k))) return n->v;
    i = (i + 1) & mask;
  }
}
Value tab_getint(Table *t, lint k) {
  if ((uint64_t)(k - 1) < t->asize) return t->arr[k - 1];
  if (!t->hcap) return NILV;
  uint32_t mask = t->hcap - 1, i = hash_int(k) & mask;
  for (;;) {
    HNode *n = &t->node[i];
    if (n->k.t == T_NIL) return NILV;
    if (n->k.t == T_INT && n->k.u.i == k) return n->v;
    i = (i + 1) & mask;
  }
}
Value tab_get(Table *t, Value k) {
  switch (k.t) {
    case T_NIL: return NILV;
    case T_INT: return tab_getint(t, k.u.i);
    case T_STR: return tab_getstr(t, strof(k));
    case T_FLT: { lint i; if (dbl2int(k.u.n, &i)) return tab_getint(t, i); }
    /* fallthrough */
    default: { int s = hfind(t, k, hash_val(k)); return s < 0 ? NILV : t->node[s].v; }
  }
}

static void hset(Table *t, Value k, Value v) {
  uint32_t h = hash_val(k);
  int s = hfind(t, k, h);
  if (s >= 0) { t->node[s].v = v; return; }
  if (v.t == T_NIL) return;
  if ((t->hused + 1) * 4 > t->hcap * 3) {
    rehash(t, 1, k);
    if (k.t == T_INT) { tab_setint(NULL, t, k.u.i, v); return; }
  }
  uint32_t mask = t->hcap - 1, i = h & mask;
  while (t->node[i].k.t != T_NIL) i = (i + 1) & mask;
  t->node[i].k = k; t->node[i].v = v; t->hused++;
}

static void append_arr(Table *t, Value v) {
  if (t->asize == t->acap) tab_reserve_arr(t, t->acap ? t->acap * 2 : 4);
  t->arr[t->asize++] = v;
}
static void migrate(Table *t) {
  while (t->hused) {
    lint k = (lint)t->asize + 1;
    uint32_t mask = t->hcap - 1, i = hash_int(k) & mask; int found = -1;
    for (;;) {
      HNode *n = &t->node[i];
      if (n->k.t == T_NIL) break;
      if (n->k.t == T_INT && n->k.u.i == k) { found = (int)i; break; }
      i = (i + 1) & mask;
    }
    if (found < 0 || t->node[found].v.t == T_NIL) return;
    Value v = t->node[found].v; t->node[found].v = NILV;
    append_arr(t, v);
  }
}

void tab_setint(State *L, Table *t, lint k, Value v) {
  (void)L;
  if ((uint64_t)(k - 1) < t->asize) {
    t->arr[k - 1] = v;
    if (v.t == T_NIL && (uint32_t)k == t->asize) {
      uint32_t a = t->asize - 1;
      while (a > 0 && t->arr[a - 1].t == T_NIL) a--;
      t->asize = a;
    }
    return;
  }
  if (k == (lint)t->asize + 1) {
    if (v.t == T_NIL) return;
    append_arr(t, v);
    if (t->hused) migrate(t);
    return;
  }
  hset(t, mkint(k), v);
}

void tab_set(State *L, Table *t, Value k, Value v) {
  switch (k.t) {
    case T_INT: tab_setint(L, t, k.u.i, v); return;
    case T_NIL: lerror(L, "table index is nil");
    case T_FLT: {
      lint i;
      if (dbl2int(k.u.n, &i)) { tab_setint(L, t, i, v); return; }
      if (k.u.n != k.u.n) lerror(L, "table index is NaN");
      hset(t, k, v); return;
    }
    default: hset(t, k, v);
  }
}
void tab_setstr(State *L, Table *t, Str *k, Value v) { (void)L; hset(t, mkstr(k), v); }

void tab_ctor_set(State *L, Table *t, lint idx, Value v) {
  if (t->hused == 0 && idx >= 1 && idx <= 0x7fffffff) {
    if ((uint32_t)idx > t->acap) tab_reserve_arr(t, (uint32_t)idx > t->acap * 2 ? (uint32_t)idx : t->acap * 2);
    t->arr[idx - 1] = v;
    if (v.t != T_NIL && (uint32_t)idx > t->asize) t->asize = (uint32_t)idx;
  } else tab_setint(L, t, idx, v);
}

lint tab_len(Table *t) {
  if (t->asize) return (lint)t->asize;
  if (t->hused) { /* defensive: border search in hash part */
    lint n = 0;
    while (tab_getint(t, n + 1).t != T_NIL) n++;
    return n;
  }
  return 0;
}

int tab_iter(Table *t, size_t *cursor, Value *k, Value *v) {
  uint32_t ai = (uint32_t)(*cursor & 0xffffffffu), hi = (uint32_t)(*cursor >> 32);
  for (; ai < t->asize; ai++)
    if (t->arr[ai].t != T_NIL) { *k = mkint((lint)ai + 1); *v = t->arr[ai]; *cursor = (size_t)(ai + 1) | ((size_t)hi << 32); return 1; }
  if (ai < t->asize) ai = t->asize;
  for (; hi < t->hcap; hi++)
    if (t->node[hi].k.t != T_NIL && t->node[hi].v.t != T_NIL) {
      *k = t->node[hi].k; *v = t->node[hi].v; *cursor = (size_t)ai | ((size_t)(hi + 1) << 32); return 1;
    }
  return 0;
}

int tab_next(State *L, Table *t, Value *key, Value *val) {
  size_t cur;
  Value k = *key;
  if (k.t == T_FLT) { lint i; if (dbl2int(k.u.n, &i)) k = mkint(i); }
  if (k.t == T_NIL) cur = 0;
  else if (k.t == T_INT && (uint64_t)(k.u.i - 1) < t->asize) cur = (size_t)k.u.i;
  else {
    int s = hfind(t, k, hash_val(k));
    if (s >= 0) cur = (size_t)t->asize | ((size_t)(s + 1) << 32);
    else if (k.t == T_INT && (uint64_t)(k.u.i - 1) < t->acap) cur = (size_t)t->asize;
    else lerror(L, "invalid key to 'next'");
  }
  return tab_iter(t, &cur, key, val);
}
