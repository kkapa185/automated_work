/* utf8 library */
#include "lua.h"

#define MAXUNICODE 0x10FFFFu
#define MAXUTF 0x7FFFFFFFu
#define iscont(p) ((*(p) & 0xC0) == 0x80)

static lint u_posrelat(lint pos, size_t len) {
  if (pos >= 0) return pos;
  if ((size_t)(-pos) > len) return 0;
  return (lint)len + pos + 1;
}
static const char *utf8_decode(const char *s, unsigned int *val, int strict) {
  static const unsigned int limits[] = {~(unsigned int)0, 0x80, 0x800, 0x10000u, 0x200000u, 0x4000000u};
  unsigned int c = (unsigned char)s[0], res = 0;
  if (c < 0x80) res = c;
  else {
    int count = 0;
    for (; c & 0x40; c <<= 1) {
      unsigned int cc = (unsigned char)s[++count];
      if ((cc & 0xC0) != 0x80) return NULL;
      res = (res << 6) | (cc & 0x3F);
    }
    res |= ((unsigned int)(c & 0x7F) << (count * 5));
    if (count > 5 || res > MAXUTF || res < limits[count]) return NULL;
    s += count;
  }
  if (strict && (res > MAXUNICODE || (0xD800u <= res && res <= 0xDFFFu))) return NULL;
  if (val) *val = res;
  return s + 1;
}
static void encode(LBuf *b, unsigned long x) {
  char buf[8]; int n = 1;
  if (x < 0x80) buf[7] = (char)x;
  else {
    unsigned int mfb = 0x3f;
    do { buf[8 - (n++)] = (char)(0x80 | (x & 0x3f)); x >>= 6; mfb >>= 1; } while (x > mfb);
    buf[8 - n] = (char)(((~mfb << 1) | x) & 0xFF);
  }
  lbuf_add(b, buf + 8 - n, (size_t)n);
}
static int utf8_char_fn(State *L, Value *a, int n) {
  LBuf b; lbuf_init(&b);
  for (int i = 0; i < n; i++) {
    lint c = arg_int(L, a, n, i);
    if ((luint)c > MAXUTF) { lbuf_free(&b); arg_error(L, i, "value out of range"); }
    encode(&b, (unsigned long)c);
  }
  return ret1(L, lbuf_finish(&b));
}
static int u_len(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0); size_t len = s->len;
  lint posi = u_posrelat(arg_optint(L, a, n, 1, 1), len), posj = u_posrelat(arg_optint(L, a, n, 2, -1), len);
  int lax = n >= 4 && truthy(a[3]);
  if (!(1 <= posi && --posi <= (lint)len)) arg_error(L, 1, "initial position out of bounds");
  if (!(--posj < (lint)len)) arg_error(L, 2, "final position out of bounds");
  lint cnt = 0;
  while (posi <= posj) {
    const char *s1 = utf8_decode(s->data + posi, NULL, !lax);
    if (s1 == NULL) { L->ret[0] = NILV; L->ret[1] = mkint(posi + 1); return 2; }
    posi = s1 - s->data; cnt++;
  }
  return ret1(L, mkint(cnt));
}
static int u_codepoint(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0); size_t len = s->len;
  lint i = u_posrelat(arg_optint(L, a, n, 1, 1), len);
  lint pose = u_posrelat(arg_optint(L, a, n, 2, i), len);
  int lax = n >= 4 && truthy(a[3]);
  if (i < 1) arg_error(L, 1, "out of bounds");
  if (pose > (lint)len) arg_error(L, 2, "out of bounds");
  if (i > pose) return 0;
  if (pose - i >= 1000000) lerror(L, "string slice too long");
  ret_need(L, (int)(pose - i) + 2);
  int cnt = 0;
  const char *p = s->data + i - 1, *e = s->data + pose;
  while (p < e) {
    unsigned int code;
    p = utf8_decode(p, &code, !lax);
    if (p == NULL) lerror(L, "invalid UTF-8 code");
    L->ret[cnt++] = mkint(code);
  }
  return cnt;
}
static int u_offset(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0); size_t len = s->len;
  lint nn = arg_int(L, a, n, 1);
  lint posi = nn > 0 ? 1 : (lint)len + 1;
  posi = u_posrelat(arg_optint(L, a, n, 2, posi), len);
  if (!(1 <= posi && --posi <= (lint)len)) arg_error(L, 2, "position out of bounds");
  const char *d = s->data;
  if (nn == 0) { while (posi > 0 && iscont(d + posi)) posi--; return ret1(L, mkint(posi + 1)); }
  if (iscont(d + posi)) lerror(L, "initial position is a continuation byte");
  if (nn < 0) {
    while (nn < 0 && posi > 0) { do { posi--; } while (posi > 0 && iscont(d + posi)); nn++; }
  } else {
    nn--;
    while (nn > 0 && posi < (lint)len) { do { posi++; } while (iscont(d + posi)); nn--; }
  }
  if (nn == 0) return ret1(L, mkint(posi + 1));
  return ret1(L, NILV);
}
static int iter_aux(State *L, Value *a, int n, int strict) {
  Str *s = arg_str(L, a, n, 0); size_t len = s->len;
  luint i = (luint)arg_int(L, a, n, 1);
  const char *d = s->data;
  if (i < len) { while (iscont(d + i)) i++; }
  if (i >= len) return 0;
  unsigned int code;
  const char *nx = utf8_decode(d + i, &code, strict);
  if (nx == NULL || iscont(nx)) lerror(L, "invalid UTF-8 code");
  L->ret[0] = mkint((lint)i + 1); L->ret[1] = mkint(code);
  return 2;
}
static int iter_strict(State *L, Value *a, int n) { return iter_aux(L, a, n, 1); }
static int iter_lax(State *L, Value *a, int n) { return iter_aux(L, a, n, 0); }
static int u_codes(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0);
  int lax = n >= 2 && truthy(a[1]);
  if (s->len > 0 && iscont(s->data)) arg_error(L, 0, "invalid UTF-8 code");
  static CFn *fs, *fl;
  if (!fs) { fs = cfn_new(iter_strict, "for iterator", 0); fl = cfn_new(iter_lax, "for iterator", 0); gc_fix(fs); gc_fix(fl); }
  L->ret[0] = mkobj(T_CFN, lax ? fl : fs); L->ret[1] = mkstr(s); L->ret[2] = mkint(0);
  return 3;
}

void open_utf8(State *L) {
  Table *t = reg_lib(L, "utf8");
  reg_func(t, "char", utf8_char_fn); reg_func(t, "len", u_len); reg_func(t, "codepoint", u_codepoint);
  reg_func(t, "offset", u_offset); reg_func(t, "codes", u_codes);
  tab_setstr(L, t, str_newz("charpattern"), mkstr(str_new("[\0-\x7F\xC2-\xFD][\x80-\xBF]*", 14)));
}
