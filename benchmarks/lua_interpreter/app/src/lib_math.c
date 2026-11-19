/* math library */
#include "lua.h"
#include <time.h>
#include <unistd.h>

static int m_abs(State *L, Value *a, int n) {
  if (n >= 1 && a[0].t == T_INT) return ret1(L, mkint(a[0].u.i < 0 ? (lint)((luint)0 - (luint)a[0].u.i) : a[0].u.i));
  return ret1(L, mkflt(fabs(arg_num(L, a, n, 0))));
}
static Value flt_to_intval(lnum d) { lint i; return dbl2int(d, &i) ? mkint(i) : mkflt(d); }
static int m_floor(State *L, Value *a, int n) {
  if (n >= 1 && a[0].t == T_INT) return ret1(L, a[0]);
  return ret1(L, flt_to_intval(floor(arg_num(L, a, n, 0))));
}
static int m_ceil(State *L, Value *a, int n) {
  if (n >= 1 && a[0].t == T_INT) return ret1(L, a[0]);
  return ret1(L, flt_to_intval(ceil(arg_num(L, a, n, 0))));
}
static int m_sqrt(State *L, Value *a, int n) { return ret1(L, mkflt(sqrt(arg_num(L, a, n, 0)))); }
static int m_sin(State *L, Value *a, int n) { return ret1(L, mkflt(sin(arg_num(L, a, n, 0)))); }
static int m_cos(State *L, Value *a, int n) { return ret1(L, mkflt(cos(arg_num(L, a, n, 0)))); }
static int m_tan(State *L, Value *a, int n) { return ret1(L, mkflt(tan(arg_num(L, a, n, 0)))); }
static int m_asin(State *L, Value *a, int n) { return ret1(L, mkflt(asin(arg_num(L, a, n, 0)))); }
static int m_acos(State *L, Value *a, int n) { return ret1(L, mkflt(acos(arg_num(L, a, n, 0)))); }
static int m_atan(State *L, Value *a, int n) { return ret1(L, mkflt(atan2(arg_num(L, a, n, 0), arg_optnum(L, a, n, 1, 1.0)))); }
static int m_exp(State *L, Value *a, int n) { return ret1(L, mkflt(exp(arg_num(L, a, n, 0)))); }
static int m_log(State *L, Value *a, int n) {
  lnum x = arg_num(L, a, n, 0);
  if (n < 2 || isnil(a[1])) return ret1(L, mkflt(log(x)));
  lnum b = arg_num(L, a, n, 1);
  if (b == 2.0) return ret1(L, mkflt(log2(x)));
  if (b == 10.0) return ret1(L, mkflt(log10(x)));
  return ret1(L, mkflt(log(x) / log(b)));
}
static int m_fmod(State *L, Value *a, int n) {
  if (n >= 2 && a[0].t == T_INT && a[1].t == T_INT) {
    lint d = a[1].u.i;
    if ((luint)d + 1u <= 1u) {
      if (d == 0) arg_error(L, 1, "zero");
      return ret1(L, mkint(0));
    }
    return ret1(L, mkint(a[0].u.i % d));
  }
  return ret1(L, mkflt(fmod(arg_num(L, a, n, 0), arg_num(L, a, n, 1))));
}
static int m_modf(State *L, Value *a, int n) {
  if (n >= 1 && a[0].t == T_INT) { L->ret[0] = a[0]; L->ret[1] = mkflt(0.0); return 2; }
  lnum x = arg_num(L, a, n, 0);
  lnum ip = x < 0 ? ceil(x) : floor(x);
  L->ret[0] = mkflt(ip);
  L->ret[1] = mkflt(isinf(x) ? 0.0 : x - ip);
  return 2;
}
static int m_tointeger(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  lint i;
  if (tointeger_v(a[0], &i) && a[0].t != T_STR) return ret1(L, mkint(i));
  if (a[0].t == T_STR && tointeger_v(a[0], &i)) return ret1(L, mkint(i));
  return ret1(L, NILV);
}
static int m_type(State *L, Value *a, int n) {
  arg_any(L, a, n, 0);
  if (a[0].t == T_INT) return ret1(L, mkstr(str_newz("integer")));
  if (a[0].t == T_FLT) return ret1(L, mkstr(str_newz("float")));
  return ret1(L, NILV);
}
static int m_deg(State *L, Value *a, int n) { return ret1(L, mkflt(arg_num(L, a, n, 0) * (180.0 / 3.141592653589793238462643383279502884))); }
static int m_rad(State *L, Value *a, int n) { return ret1(L, mkflt(arg_num(L, a, n, 0) * (3.141592653589793238462643383279502884 / 180.0))); }
static int m_frexp(State *L, Value *a, int n) {
  int e; lnum m = frexp(arg_num(L, a, n, 0), &e);
  L->ret[0] = mkflt(m); L->ret[1] = mkint(e); return 2;
}
static int m_ldexp(State *L, Value *a, int n) {
  lnum m = arg_num(L, a, n, 0); lint e = arg_int(L, a, n, 1);
  if (e > 100000) e = 100000; else if (e < -100000) e = -100000;
  return ret1(L, mkflt(ldexp(m, (int)e)));
}
static int m_ult(State *L, Value *a, int n) { return ret1(L, mkbool((luint)arg_int(L, a, n, 0) < (luint)arg_int(L, a, n, 1))); }
static int m_max(State *L, Value *a, int n) {
  arg_num(L, a, n, 0);
  Value best; tonumber_v(a[0], &best);
  for (int i = 1; i < n; i++) { arg_num(L, a, n, i); Value v; tonumber_v(a[i], &v); if (num_lt(best, v)) best = v; }
  return ret1(L, best);
}
static int m_min(State *L, Value *a, int n) {
  arg_num(L, a, n, 0);
  Value best; tonumber_v(a[0], &best);
  for (int i = 1; i < n; i++) { arg_num(L, a, n, i); Value v; tonumber_v(a[i], &v); if (num_lt(v, best)) best = v; }
  return ret1(L, best);
}

/* xoshiro256** */
static uint64_t rs[4];
static inline uint64_t rotl(uint64_t x, int n) { return (x << n) | (x >> (64 - n)); }
static uint64_t xo_next(void) {
  uint64_t result = rotl(rs[1] * 5, 7) * 9, t = rs[1] << 17;
  rs[2] ^= rs[0]; rs[3] ^= rs[1]; rs[1] ^= rs[2]; rs[0] ^= rs[3]; rs[2] ^= t; rs[3] = rotl(rs[3], 45);
  return result;
}
static void setseed(uint64_t n1, uint64_t n2) {
  rs[0] = n1; rs[1] = 0xff; rs[2] = n2; rs[3] = 0;
  for (int i = 0; i < 16; i++) xo_next();
}
static uint64_t project(uint64_t ran, uint64_t n) {
  if ((n & (n + 1)) == 0) return ran & n;
  uint64_t lim = n;
  lim |= lim >> 1; lim |= lim >> 2; lim |= lim >> 4; lim |= lim >> 8; lim |= lim >> 16; lim |= lim >> 32;
  while ((ran &= lim) > n) ran = xo_next();
  return ran;
}
static int m_random(State *L, Value *a, int n) {
  uint64_t rv = xo_next();
  lint low, up;
  switch (n) {
    case 0: return ret1(L, mkflt((lnum)(rv >> 11) * (0.5 / ((uint64_t)1 << 52))));
    case 1:
      low = 1; up = arg_int(L, a, n, 0);
      if (up == 0) return ret1(L, mkint((lint)rv));
      break;
    case 2: low = arg_int(L, a, n, 0); up = arg_int(L, a, n, 1); break;
    default: lerror(L, "wrong number of arguments");
  }
  if (low > up) arg_error(L, n - 1, "interval is empty");
  return ret1(L, mkint((lint)(project(rv, (uint64_t)up - (uint64_t)low) + (uint64_t)low)));
}
static int m_randomseed(State *L, Value *a, int n) {
  uint64_t n1, n2;
  if (n == 0) { n1 = (uint64_t)time(NULL) ^ ((uint64_t)getpid() << 32); n2 = (uint64_t)(uintptr_t)L; }
  else {
    if (a[0].t == T_FLT) { lint i; if (dbl2int(a[0].u.n, &i)) n1 = (uint64_t)i; else memcpy(&n1, &a[0].u.n, 8); }
    else n1 = (uint64_t)arg_int(L, a, n, 0);
    n2 = (uint64_t)arg_optint(L, a, n, 1, 0);
  }
  setseed(n1, n2);
  L->ret[0] = mkint((lint)n1); L->ret[1] = mkint((lint)n2);
  return 2;
}

void open_math(State *L) {
  Table *t = reg_lib(L, "math");
  reg_func(t, "abs", m_abs); reg_func(t, "floor", m_floor); reg_func(t, "ceil", m_ceil); reg_func(t, "sqrt", m_sqrt);
  reg_func(t, "sin", m_sin); reg_func(t, "cos", m_cos); reg_func(t, "tan", m_tan); reg_func(t, "asin", m_asin);
  reg_func(t, "acos", m_acos); reg_func(t, "atan", m_atan); reg_func(t, "exp", m_exp); reg_func(t, "log", m_log);
  reg_func(t, "fmod", m_fmod); reg_func(t, "deg", m_deg); reg_func(t, "rad", m_rad); reg_func(t, "frexp", m_frexp); reg_func(t, "ldexp", m_ldexp); reg_func(t, "modf", m_modf);
  reg_func(t, "tointeger", m_tointeger); reg_func(t, "type", m_type); reg_func(t, "ult", m_ult);
  reg_func(t, "max", m_max); reg_func(t, "min", m_min); reg_func(t, "random", m_random); reg_func(t, "randomseed", m_randomseed);
  tab_setstr(L, t, str_newz("pi"), mkflt(3.141592653589793238462643383279502884));
  tab_setstr(L, t, str_newz("huge"), mkflt(HUGE_VAL));
  tab_setstr(L, t, str_newz("maxinteger"), mkint(INT64_MAX));
  tab_setstr(L, t, str_newz("mininteger"), mkint(INT64_MIN));
  setseed((uint64_t)time(NULL) ^ ((uint64_t)getpid() << 32), (uint64_t)(uintptr_t)L);
}
