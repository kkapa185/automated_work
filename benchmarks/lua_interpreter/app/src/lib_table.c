/* table library */
#include "lua.h"
#include <limits.h>

static Value check_tab(State *L, Value *a, int n, int i) {
  if (i < n) {
    if (a[i].t == T_TABLE) return a[i];
    Table *mt = getmetatable_of(a[i]);
    if (mt && a[i].t != T_STR && !isnil(tab_getstr(mt, G.tmname[TM_INDEX])) &&
        !isnil(tab_getstr(mt, G.tmname[TM_NEWINDEX])) && !isnil(tab_getstr(mt, G.tmname[TM_LEN]))) return a[i];
  }
  arg_typeerror(L, i, "table", a, n);
}
static lint len_of(State *L, Value t) {
  if (t.t == T_TABLE && !tabof(t)->meta) return tab_len(tabof(t));
  int ok; Value r = len_val(L, t, &ok);
  lint x;
  if (!ok || !tointeger_num(r, &x)) lerror(L, "object length is not an integer");
  return x;
}

static int t_insert(State *L, Value *a, int n) {
  Value t = check_tab(L, a, n, 0);
  lint e = len_of(L, t) + 1, pos;
  switch (n) {
    case 2: pos = e; break;
    case 3: {
      pos = arg_int(L, a, n, 1);
      if ((luint)pos - 1u >= (luint)e) arg_error(L, 1, "position out of bounds");
      for (lint i = e; i > pos; i--) seti_v(L, t, i, geti_v(L, t, i - 1));
      break;
    }
    default: lerror(L, "wrong number of arguments to 'insert'");
  }
  seti_v(L, t, pos, a[n - 1]);
  return 0;
}
static int t_remove(State *L, Value *a, int n) {
  Value t = check_tab(L, a, n, 0);
  lint size = len_of(L, t), pos = arg_optint(L, a, n, 1, size);
  if (n >= 2 && pos != size && (luint)pos - 1u > (luint)size) arg_error(L, 1, "position out of bounds");
  Value v = geti_v(L, t, pos);
  for (; pos < size; pos++) seti_v(L, t, pos, geti_v(L, t, pos + 1));
  seti_v(L, t, pos, NILV);
  return ret1(L, v);
}
static int t_concat(State *L, Value *a, int n) {
  Value t = check_tab(L, a, n, 0);
  Str *sep = n >= 2 && !isnil(a[1]) ? arg_str(L, a, n, 1) : NULL;
  lint i = arg_optint(L, a, n, 2, 1), j = n >= 4 && !isnil(a[3]) ? arg_int(L, a, n, 3) : len_of(L, t);
  LBuf b; lbuf_init(&b);
  for (lint k = i; k <= j; k++) {
    Value v = geti_v(L, t, k);
    if (v.t == T_STR) lbuf_add(&b, strof(v)->data, strof(v)->len);
    else if (isnum(v)) { char tmp[64]; int l = fmt_number(tmp, v); lbuf_add(&b, tmp, (size_t)l); }
    else { lbuf_free(&b); lerror(L, "invalid value (at index %lld) in table for 'concat'", (long long)k); }
    if (sep && k < j) lbuf_add(&b, sep->data, sep->len);
    if (k == INT64_MAX) break;
  }
  return ret1(L, lbuf_finish(&b));
}
static int t_unpack(State *L, Value *a, int n) {
  Value t = argv(a, n, 0);
  lint i = arg_optint(L, a, n, 1, 1), e = n >= 3 && !isnil(a[2]) ? arg_int(L, a, n, 2) : len_of(L, t);
  if (i > e) return 0;
  luint cnt = (luint)e - (luint)i;
  if (cnt >= 10000000u) lerror(L, "too many results to unpack");
  int c = (int)cnt + 1;
  if (stack_avail(L) < (size_t)c * sizeof(Value) + 131072) lerror(L, "too many results to unpack");
  ret_need(L, c + 1);
  if (t.t == T_TABLE && !tabof(t)->meta) for (int k = 0; k < c; k++) L->ret[k] = tab_getint(tabof(t), i + k);
  else {
    Value *tmp = alloca((size_t)c * sizeof(Value));
    for (int k = 0; k < c; k++) tmp[k] = geti_v(L, t, i + k);
    memcpy(L->ret, tmp, (size_t)c * sizeof(Value));
  }
  return c;
}
static int t_create(State *L, Value *a, int n) {
  lint nseq = arg_int(L, a, n, 0), nrec = arg_optint(L, a, n, 1, 0);
  if (nseq < 0 || nseq > INT_MAX) arg_error(L, 0, "out of range");
  if (nrec < 0 || nrec > INT_MAX) arg_error(L, 1, "out of range");
  if (nseq > 100000000 || nrec > 100000000) lerror(L, "table overflow");
  return ret1(L, mktab(tab_new((int)nseq, (int)nrec)));
}
static int t_pack(State *L, Value *a, int n) {
  Table *t = tab_new(n, 1);
  for (int i = 0; i < n; i++) tab_setint(L, t, i + 1, a[i]);
  tab_setstr(L, t, str_newz("n"), mkint(n));
  return ret1(L, mktab(t));
}
static int t_move(State *L, Value *a, int n) {
  Value a1 = check_tab(L, a, n, 0);
  lint f = arg_int(L, a, n, 1), e = arg_int(L, a, n, 2), t = arg_int(L, a, n, 3);
  Value tt = n >= 5 && !isnil(a[4]) ? check_tab(L, a, n, 4) : a1;
  if (e >= f) {
    if (!(f > 0 || e < INT64_MAX + f)) arg_error(L, 2, "too many elements to move");
    lint cnt = e - f + 1;
    if (t > INT64_MAX - cnt + 1) arg_error(L, 3, "destination wrap around");
    if (t > e || t <= f || (n >= 5 && !isnil(a[4]) && !raw_equal(a1, tt)))
      for (lint i = 0; i < cnt; i++) seti_v(L, tt, t + i, geti_v(L, a1, f + i));
    else
      for (lint i = cnt - 1; i >= 0; i--) seti_v(L, tt, t + i, geti_v(L, a1, f + i));
  }
  return ret1(L, tt);
}

/* ---------- sort (introsort on indices) ---------- */
typedef struct SortCtx { State *L; Value t; Value cmp; } SortCtx;
static int sort_lt(SortCtx *c, Value x, Value y) {
  if (isnil(c->cmp)) return val_lt(c->L, x, y);
  Value args[2] = {x, y};
  return truthy(call1(c->L, c->cmp, args, 2));
}
#define GET(i) geti_v(c->L, c->t, (i))
#define SET(i, v) seti_v(c->L, c->t, (i), (v))
static void swap_idx(SortCtx *c, lint i, lint j) { Value x = GET(i), y = GET(j); SET(i, y); SET(j, x); }
static void insertion(SortCtx *c, lint lo, lint hi) {
  for (lint i = lo + 1; i <= hi; i++) {
    Value v = GET(i); lint j = i - 1;
    while (j >= lo) {
      Value w = GET(j);
      if (!sort_lt(c, v, w)) break;
      SET(j + 1, w); j--;
    }
    SET(j + 1, v);
  }
}
static void sift(SortCtx *c, lint base, lint root, lint cnt) {
  for (;;) {
    lint child = 2 * root + 1;
    if (child >= cnt) return;
    if (child + 1 < cnt && sort_lt(c, GET(base + child), GET(base + child + 1))) child++;
    if (!sort_lt(c, GET(base + root), GET(base + child))) return;
    swap_idx(c, base + root, base + child); root = child;
  }
}
static void heapsort_range(SortCtx *c, lint lo, lint hi) {
  lint cnt = hi - lo + 1;
  for (lint i = cnt / 2 - 1; i >= 0; i--) sift(c, lo, i, cnt);
  for (lint e = cnt - 1; e > 0; e--) { swap_idx(c, lo, lo + e); sift(c, lo, 0, e); }
}
static void auxsort(SortCtx *c, lint lo, lint up, int depth) {
  while (lo < up) {
    if (up - lo < 12) { insertion(c, lo, up); return; }
    if (depth-- <= 0) { heapsort_range(c, lo, up); return; }
    lint mid = lo + (up - lo) / 2;
    if (sort_lt(c, GET(mid), GET(lo))) swap_idx(c, mid, lo);
    if (sort_lt(c, GET(up), GET(mid))) { swap_idx(c, mid, up); if (sort_lt(c, GET(mid), GET(lo))) swap_idx(c, mid, lo); }
    Value P = GET(mid);
    swap_idx(c, mid, up - 1);
    lint i = lo, j = up - 1;
    for (;;) {
      while (sort_lt(c, GET(++i), P)) if (i >= up) lerror(c->L, "invalid order function for sorting");
      while (sort_lt(c, P, GET(--j))) if (j <= lo) lerror(c->L, "invalid order function for sorting");
      if (j < i) break;
      swap_idx(c, i, j);
    }
    swap_idx(c, up - 1, i);
    if (i - lo < up - i) { auxsort(c, lo, i - 1, depth); lo = i + 1; }
    else { auxsort(c, i + 1, up, depth); up = i - 1; }
  }
}
static int t_sort(State *L, Value *a, int n) {
  Value t = check_tab(L, a, n, 0);
  lint sz = len_of(L, t);
  if (sz > 1) {
    if (sz >= INT_MAX) arg_error(L, 0, "array too big");
    if (n >= 2 && !isnil(a[1]) && a[1].t != T_LCL && a[1].t != T_CFN) arg_typeerror(L, 1, "function", a, n);
    SortCtx c = {L, t, n >= 2 ? a[1] : NILV};
    int depth = 0; for (lint s = sz; s > 0; s >>= 1) depth += 2;
    auxsort(&c, 1, sz, depth);
  }
  return 0;
}

void open_table(State *L) {
  Table *t = reg_lib(L, "table");
  reg_func(t, "insert", t_insert); reg_func(t, "remove", t_remove); reg_func(t, "concat", t_concat);
  reg_func(t, "unpack", t_unpack); reg_func(t, "pack", t_pack); reg_func(t, "create", t_create); reg_func(t, "move", t_move); reg_func(t, "sort", t_sort);
  tab_setstr(L, G.globals, str_newz("unpack"), NILV);
}
