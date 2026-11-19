/* Values: conversions, comparison, metamethod-aware operations. */
#include "lua.h"
#include <ctype.h>
#include <inttypes.h>

const char *typename_of(int t) {
  switch (t) {
    case T_NIL: return "nil"; case T_BOOL: return "boolean"; case T_INT: case T_FLT: return "number";
    case T_STR: return "string"; case T_TABLE: return "table"; case T_LCL: case T_CFN: return "function";
    case T_THREAD: return "thread"; default: return "userdata";
  }
}
const char *objtypename(Value v) {
  Table *mt = getmetatable_of(v);
  if (mt && (v.t == T_TABLE || v.t == T_UDATA)) {
    Value n = tab_getstr(mt, G.tmname[TM_NAME]);
    if (n.t == T_STR) return strof(n)->data;
  }
  return typename_of(v.t);
}

int dbl2int(double d, lint *out) {
  if (d >= -9223372036854775808.0 && d < 9223372036854775808.0) {
    lint i = (lint)d;
    if ((double)i == d) { *out = i; return 1; }
  }
  return 0;
}

int str2number(const char *s, size_t len, Value *out) {
  const char *p = s, *e = s + len;
  while (p < e && isspace((unsigned char)*p)) p++;
  while (e > p && isspace((unsigned char)e[-1])) e--;
  if (p == e) return 0;
  int neg = 0;
  if (*p == '-') { neg = 1; p++; } else if (*p == '+') p++;
  if (p == e) return 0;
  if (p + 1 < e && p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
    p += 2;
    uint64_t mi = 0; double md = 0; int any = 0, isf = 0, exp = 0;
    for (; p < e && isxdigit((unsigned char)*p); p++) {
      int d = isdigit((unsigned char)*p) ? *p - '0' : (tolower((unsigned char)*p) - 'a' + 10);
      mi = mi * 16 + (uint64_t)d; md = md * 16 + d; any = 1;
    }
    if (p < e && *p == '.') {
      isf = 1; p++;
      for (; p < e && isxdigit((unsigned char)*p); p++) {
        int d = isdigit((unsigned char)*p) ? *p - '0' : (tolower((unsigned char)*p) - 'a' + 10);
        md = md * 16 + d; exp -= 4; any = 1;
      }
    }
    if (!any) return 0;
    if (p < e && (*p == 'p' || *p == 'P')) {
      isf = 1; p++;
      int eneg = 0, ev = 0, edig = 0;
      if (p < e && (*p == '+' || *p == '-')) { eneg = *p == '-'; p++; }
      for (; p < e && isdigit((unsigned char)*p); p++) { if (ev < 100000) ev = ev * 10 + (*p - '0'); edig = 1; }
      if (!edig) return 0;
      exp += eneg ? -ev : ev;
    }
    if (p != e) return 0;
    if (!isf) { lint r = (lint)(neg ? (uint64_t)0 - mi : mi); *out = mkint(r); return 1; }
    double r = ldexp(md, exp); *out = mkflt(neg ? -r : r); return 1;
  }
  const char *q = p; int digits = 0, isf = 0;
  while (q < e && isdigit((unsigned char)*q)) { q++; digits++; }
  if (q < e && *q == '.') { isf = 1; q++; while (q < e && isdigit((unsigned char)*q)) { q++; digits++; } }
  if (!digits) return 0;
  if (q < e && (*q == 'e' || *q == 'E')) {
    isf = 1; q++;
    if (q < e && (*q == '+' || *q == '-')) q++;
    int ed = 0; while (q < e && isdigit((unsigned char)*q)) { q++; ed++; }
    if (!ed) return 0;
  }
  if (q != e) return 0;
  if (!isf) {
    uint64_t v = 0; int ovf = 0;
    for (const char *c = p; c < e; c++) {
      int d = *c - '0';
      if (v > (UINT64_MAX - (uint64_t)d) / 10) { ovf = 1; break; }
      v = v * 10 + (uint64_t)d;
    }
    if (!ovf && (v <= (uint64_t)INT64_MAX || (neg && v == (uint64_t)INT64_MAX + 1))) {
      *out = mkint(neg ? (lint)((uint64_t)0 - v) : (lint)v); return 1;
    }
  }
  char buf[400]; size_t n = (size_t)(e - p);
  char *tmp = n < sizeof buf ? buf : malloc(n + 1);
  memcpy(tmp, p, n); tmp[n] = 0;
  double d = strtod(tmp, NULL);
  if (tmp != buf) free(tmp);
  *out = mkflt(neg ? -d : d);
  return 1;
}

int fmt_number(char *buf, Value v) {
  if (v.t == T_INT) {
    char tmp[24]; int n = 0; luint u = v.u.i < 0 ? (luint)0 - (luint)v.u.i : (luint)v.u.i;
    do { tmp[n++] = (char)('0' + u % 10); u /= 10; } while (u);
    int len = 0; if (v.u.i < 0) buf[len++] = '-';
    while (n) buf[len++] = tmp[--n];
    buf[len] = 0; return len;
  }
  int n = snprintf(buf, 64, "%.14g", v.u.n);
  if (buf[strspn(buf, "-0123456789")] == '\0') { buf[n++] = '.'; buf[n++] = '0'; buf[n] = 0; }
  return n;
}

int tonumber_v(Value v, Value *out) {
  if (isnum(v)) { *out = v; return 1; }
  if (v.t == T_STR) return str2number(strof(v)->data, strof(v)->len, out);
  return 0;
}
int tointeger_num(Value v, lint *out) {
  if (v.t == T_INT) { *out = v.u.i; return 1; }
  if (v.t == T_FLT) return dbl2int(v.u.n, out);
  return 0;
}
int tointeger_v(Value v, lint *out) {
  Value x;
  if (!tonumber_v(v, &x)) return 0;
  return tointeger_num(x, out);
}

Value tostring_basic(Value v) {
  char buf[96];
  switch (v.t) {
    case T_NIL: return mkstr(str_newz("nil"));
    case T_BOOL: return mkstr(str_newz(v.u.b ? "true" : "false"));
    case T_INT: case T_FLT: { int n = fmt_number(buf, v); return mkstr(str_new(buf, (size_t)n)); }
    case T_STR: return v;
    default: {
      const char *tn = v.t == T_TABLE ? "table" : (v.t == T_LCL || v.t == T_CFN) ? "function"
                       : v.t == T_THREAD ? "thread" : "userdata";
      snprintf(buf, sizeof buf, "%s: %p", tn, v.u.p);
      return mkstr(str_newz(buf));
    }
  }
}
Value tostring_meta(State *L, Value v) {
  if (v.t == T_TABLE || v.t == T_UDATA) {
    Value tm = get_tm(v, TM_TOSTRING);
    if (!isnil(tm)) {
      Value args[1] = {v};
      Value r = call1(L, tm, args, 1);
      if (r.t != T_STR) {
        if (isnum(r)) return tostring_basic(r);
        lerror(L, "'__tostring' must return a string");
      }
      return r;
    }
    Table *mt = getmetatable_of(v);
    if (mt) {
      Value n = tab_getstr(mt, G.tmname[TM_NAME]);
      if (n.t == T_STR) {
        char buf[200]; snprintf(buf, sizeof buf, "%s: %p", strof(n)->data, v.u.p);
        return mkstr(str_newz(buf));
      }
    }
  }
  return tostring_basic(v);
}

/* ---------- equality / order ---------- */
static int eq_int_flt(lint i, double f) { lint j; return dbl2int(f, &j) && j == i; }
int raw_equal(Value a, Value b) {
  if (a.t != b.t) {
    if (a.t == T_INT && b.t == T_FLT) return eq_int_flt(a.u.i, b.u.n);
    if (a.t == T_FLT && b.t == T_INT) return eq_int_flt(b.u.i, a.u.n);
    return 0;
  }
  switch (a.t) {
    case T_NIL: return 1;
    case T_BOOL: return a.u.b == b.u.b;
    case T_INT: return a.u.i == b.u.i;
    case T_FLT: return a.u.n == b.u.n;
    case T_STR: return str_eq(strof(a), strof(b));
    default: return a.u.p == b.u.p;
  }
}
int val_equal(State *L, Value a, Value b) {
  if (raw_equal(a, b)) return 1;
  if (a.t != b.t || (a.t != T_TABLE && a.t != T_UDATA)) return 0;
  Value tm = get_tm(a, TM_EQ);
  if (isnil(tm)) tm = get_tm(b, TM_EQ);
  if (isnil(tm)) return 0;
  Value args[2] = {a, b};
  return truthy(call1(L, tm, args, 2));
}
static int lt_int_flt(lint i, double f) {
  if (f != f) return 0;
  if (f >= 9223372036854775808.0) return 1;
  if (f > -9223372036854775808.0) return i < (lint)ceil(f);
  return 0;
}
static int le_int_flt(lint i, double f) {
  if (f != f) return 0;
  if (f >= 9223372036854775808.0) return 1;
  if (f >= -9223372036854775808.0) return i <= (lint)floor(f);
  return 0;
}
static int lt_flt_int(double f, lint i) {
  if (f != f) return 0;
  if (f >= 9223372036854775808.0) return 0;
  if (f >= -9223372036854775808.0) return (lint)floor(f) < i;
  return 1;
}
static int le_flt_int(double f, lint i) {
  if (f != f) return 0;
  if (f >= 9223372036854775808.0) return 0;
  if (f > -9223372036854775808.0) return (lint)ceil(f) <= i;
  return 1;
}
int num_lt(Value a, Value b) {
  if (a.t == T_INT) return b.t == T_INT ? a.u.i < b.u.i : lt_int_flt(a.u.i, b.u.n);
  return b.t == T_FLT ? a.u.n < b.u.n : lt_flt_int(a.u.n, b.u.i);
}
int num_le(Value a, Value b) {
  if (a.t == T_INT) return b.t == T_INT ? a.u.i <= b.u.i : le_int_flt(a.u.i, b.u.n);
  return b.t == T_FLT ? a.u.n <= b.u.n : le_flt_int(a.u.n, b.u.i);
}
static void cmp_error(State *L, Value a, Value b) {
  const char *t1 = objtypename(a), *t2 = objtypename(b);
  if (strcmp(t1, t2) == 0) lerror(L, "attempt to compare two %s values", t1);
  lerror(L, "attempt to compare %s with %s", t1, t2);
}
int val_lt(State *L, Value a, Value b) {
  if (isnum(a) && isnum(b)) return num_lt(a, b);
  if (a.t == T_STR && b.t == T_STR) return str_cmp(strof(a), strof(b)) < 0;
  Value tm = get_tm(a, TM_LT);
  if (isnil(tm)) tm = get_tm(b, TM_LT);
  if (isnil(tm)) cmp_error(L, a, b);
  Value args[2] = {a, b};
  return truthy(call1(L, tm, args, 2));
}
int val_le(State *L, Value a, Value b) {
  if (isnum(a) && isnum(b)) return num_le(a, b);
  if (a.t == T_STR && b.t == T_STR) return str_cmp(strof(a), strof(b)) <= 0;
  Value tm = get_tm(a, TM_LE);
  if (isnil(tm)) tm = get_tm(b, TM_LE);
  if (isnil(tm)) cmp_error(L, a, b);
  Value args[2] = {a, b};
  return truthy(call1(L, tm, args, 2));
}

/* ---------- metatables / indexing ---------- */
Table *getmetatable_of(Value v) {
  switch (v.t) {
    case T_TABLE: return tabof(v)->meta;
    case T_UDATA: return ((Udata *)v.u.p)->meta;
    case T_STR: return G.strmeta;
    default: return NULL;
  }
}
Value get_tm(Value v, int tm) {
  Table *mt = getmetatable_of(v);
  if (!mt) return NILV;
  return tab_getstr(mt, G.tmname[tm]);
}

Value index_val(State *L, Value o, Value k, int *ok) {
  *ok = 1;
  for (int loop = 0; loop < 2000; loop++) {
    Value tm;
    if (o.t == T_TABLE) {
      Table *t = tabof(o);
      Value v = tab_get(t, k);
      if (!isnil(v) || !t->meta) return v;
      tm = tab_getstr(t->meta, G.tmname[TM_INDEX]);
      if (isnil(tm)) return NILV;
    } else {
      tm = get_tm(o, TM_INDEX);
      if (isnil(tm)) { *ok = 0; return o; }
    }
    if (tm.t == T_LCL || tm.t == T_CFN) { Value args[2] = {o, k}; return call1(L, tm, args, 2); }
    o = tm;
  }
  lerror(L, "'__index' chain too long; possible loop");
}
Value index_str(State *L, Value o, Str *k, int *ok) { return index_val(L, o, mkstr(k), ok); }

int setindex_val(State *L, Value o, Value k, Value v, Value *bad) {
  for (int loop = 0; loop < 2000; loop++) {
    Value tm;
    if (o.t == T_TABLE) {
      Table *t = tabof(o);
      if (!t->meta) { tab_set(L, t, k, v); return 1; }
      Value ex = tab_get(t, k);
      if (!isnil(ex)) { tab_set(L, t, k, v); return 1; }
      tm = tab_getstr(t->meta, G.tmname[TM_NEWINDEX]);
      if (isnil(tm)) { tab_set(L, t, k, v); return 1; }
    } else {
      tm = get_tm(o, TM_NEWINDEX);
      if (isnil(tm)) { *bad = o; return 0; }
    }
    if (tm.t == T_LCL || tm.t == T_CFN) { Value args[3] = {o, k, v}; call1(L, tm, args, 3); return 1; }
    o = tm;
  }
  lerror(L, "'__newindex' chain too long; possible loop");
}

/* ---------- arithmetic ---------- */
lint shift_left(lint a, lint n) {
  if (n <= -64 || n >= 64) return 0;
  if (n >= 0) return (lint)((luint)a << n);
  return (lint)((luint)a >> (-n));
}
lint int_idiv(State *L, lint a, lint b) {
  if (b == 0) lerror(L, "attempt to perform 'n//0'");
  if (b == -1) return (lint)((luint)0 - (luint)a);
  lint q = a / b;
  if ((a % b != 0) && ((a ^ b) < 0)) q--;
  return q;
}
lint int_mod(State *L, lint a, lint b) {
  if (b == 0) lerror(L, "attempt to perform 'n%%0'");
  if (b == -1) return 0;
  lint m = a % b;
  if (m != 0 && (m ^ b) < 0) m += b;
  return m;
}
lnum flt_mod(lnum a, lnum b) {
  lnum m = fmod(a, b);
  if ((m > 0) ? b < 0 : (m < 0 && b != m)) m += b;
  return m;
}
static inline lnum tofl(Value v) { return v.t == T_INT ? (lnum)v.u.i : v.u.n; }

static int arith_nums(State *L, int op, Value x, Value y, Value *res) {
  if (op >= OP_BAND) {
    lint i, j;
    if (!tointeger_num(x, &i) || !tointeger_num(y, &j)) return -1;
    switch (op) {
      case OP_BAND: *res = mkint(i & j); break;
      case OP_BOR: *res = mkint(i | j); break;
      case OP_BXOR: *res = mkint(i ^ j); break;
      case OP_SHL: *res = mkint(shift_left(i, j)); break;
      default: *res = mkint(shift_left(i, (lint)((luint)0 - (luint)j))); break;
    }
    return 1;
  }
  if (x.t == T_INT && y.t == T_INT && op != OP_POW && op != OP_DIV) {
    lint a = x.u.i, b = y.u.i;
    switch (op) {
      case OP_ADD: *res = mkint((lint)((luint)a + (luint)b)); break;
      case OP_SUB: *res = mkint((lint)((luint)a - (luint)b)); break;
      case OP_MUL: *res = mkint((lint)((luint)a * (luint)b)); break;
      case OP_MOD: *res = mkint(int_mod(L, a, b)); break;
      default: *res = mkint(int_idiv(L, a, b)); break;
    }
    return 1;
  }
  lnum a = tofl(x), b = tofl(y);
  switch (op) {
    case OP_ADD: *res = mkflt(a + b); break;
    case OP_SUB: *res = mkflt(a - b); break;
    case OP_MUL: *res = mkflt(a * b); break;
    case OP_DIV: *res = mkflt(a / b); break;
    case OP_POW: *res = mkflt(b == 2 ? a * a : pow(a, b)); break;
    case OP_IDIV: *res = mkflt(floor(a / b)); break;
    default: *res = mkflt(flt_mod(a, b)); break;
  }
  return 1;
}

int arith_try(State *L, int op, Value a, Value b, Value *res) {
  Value x, y;
  int ca = tonumber_v(a, &x), cb = tonumber_v(b, &y);
  if (ca && cb) return arith_nums(L, op, x, y, res);
  Value tm = get_tm(a, TM_ADD + op);
  if (isnil(tm)) tm = get_tm(b, TM_ADD + op);
  if (!isnil(tm)) { Value args[2] = {a, b}; *res = call1(L, tm, args, 2); return 1; }
  L->badop = ca ? 2 : 1;
  return 0;
}
Value arith_val(State *L, int op, Value a, Value b) {
  Value r;
  int s = arith_try(L, op, a, b, &r);
  if (s == 1) return r;
  if (s == -1) lerror(L, "number has no integer representation");
  Value bad = L->badop == 1 ? a : b;
  lerror(L, "attempt to perform %s on a %s value", op >= OP_BAND ? "bitwise operation" : "arithmetic", objtypename(bad));
}

/* ---------- concat / length ---------- */
static inline int strnum(Value v) { return v.t == T_STR || isnum(v); }

int concat_try(State *L, Value a, Value b, Value *res) {
  Value tm = get_tm(a, TM_CONCAT);
  if (isnil(tm)) tm = get_tm(b, TM_CONCAT);
  if (isnil(tm)) return 0;
  Value args[2] = {a, b};
  *res = call1(L, tm, args, 2);
  return 1;
}
static Value concat_flat(Value *v, int n) {
  size_t total = 0; char tmp[64];
  for (int i = 0; i < n; i++) total += v[i].t == T_STR ? strof(v[i])->len : (size_t)fmt_number(tmp, v[i]);
  if (total > 40) {
    Str *s = str_new_uninit(total); char *d = s->data;
    for (int i = 0; i < n; i++) {
      if (v[i].t == T_STR) { memcpy(d, strof(v[i])->data, strof(v[i])->len); d += strof(v[i])->len; }
      else { int l = fmt_number(tmp, v[i]); memcpy(d, tmp, (size_t)l); d += l; }
    }
    return mkstr(s);
  }
  char buf[48]; char *d = buf;
  for (int i = 0; i < n; i++) {
    if (v[i].t == T_STR) { memcpy(d, strof(v[i])->data, strof(v[i])->len); d += strof(v[i])->len; }
    else { int l = fmt_number(tmp, v[i]); memcpy(d, tmp, (size_t)l); d += l; }
  }
  return mkstr(str_new(buf, total));
}
Value concat_vals(State *L, Value *v, int n) {
  int all = 1;
  for (int i = 0; i < n; i++) if (!strnum(v[i])) { all = 0; break; }
  if (all) return concat_flat(v, n);
  Value acc = v[n - 1];
  for (int i = n - 2; i >= 0; i--) {
    Value l = v[i], pair[2] = {l, acc};
    if (strnum(l) && strnum(acc)) acc = concat_flat(pair, 2);
    else {
      Value r;
      if (!concat_try(L, l, acc, &r)) {
        Value bad = strnum(l) ? acc : l;
        lerror(L, "attempt to concatenate a %s value", objtypename(bad));
      }
      acc = r;
    }
  }
  return acc;
}

Value len_val(State *L, Value v, int *ok) {
  *ok = 1;
  if (v.t == T_STR) return mkint((lint)strof(v)->len);
  Value tm = get_tm(v, TM_LEN);
  if (!isnil(tm)) { Value args[1] = {v}; return call1(L, tm, args, 1); }
  if (v.t == T_TABLE) return mkint(tab_len(tabof(v)));
  *ok = 0;
  return NILV;
}
