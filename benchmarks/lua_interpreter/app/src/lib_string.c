/* string library: basic functions, Lua patterns, format, pack/unpack. */
#include "lua.h"
#include <ctype.h>
#include <limits.h>

typedef struct Buf { char *p; size_t n, cap; } Buf;
static void buf_init(Buf *b) { b->p = NULL; b->n = b->cap = 0; }
static void buf_need(Buf *b, size_t extra) {
  if (b->n + extra + 1 > b->cap) {
    size_t nc = (b->n + extra + 1) * 2; if (nc < 64) nc = 64;
    char *np = realloc(b->p, nc);
    if (!np) { fputs("lua: not enough memory\n", stderr); exit(1); }
    b->p = np; b->cap = nc;
  }
}
static void buf_add(Buf *b, const char *s, size_t l) { buf_need(b, l); memcpy(b->p + b->n, s, l); b->n += l; }
static void buf_addc(Buf *b, char c) { buf_need(b, 1); b->p[b->n++] = c; }
static Value buf_finish(Buf *b) { Str *s = str_new(b->p ? b->p : "", b->n); free(b->p); b->p = NULL; return mkstr(s); }

static size_t posrelatI(lint pos, size_t len) {
  if (pos > 0) return (size_t)pos;
  if (pos == 0) return 1;
  if (pos < -(lint)len) return 1;
  return len + (size_t)pos + 1;
}
static size_t getendpos(lint pos, size_t len) {
  if (pos > (lint)len) return len;
  if (pos >= 0) return (size_t)pos;
  if (pos < -(lint)len) return 0;
  return len + (size_t)pos + 1;
}

/* ---------- basic functions ---------- */
static int s_len(State *L, Value *a, int n) { return ret1(L, mkint((lint)arg_str(L, a, n, 0)->len)); }
static int s_sub(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0);
  size_t l = s->len, st = posrelatI(arg_int(L, a, n, 1), l), e = getendpos(arg_optint(L, a, n, 2, -1), l);
  if (st > e) return ret1(L, mkstr(str_new("", 0)));
  return ret1(L, mkstr(str_new(s->data + st - 1, e - st + 1)));
}
static int s_upper(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0); Buf b; buf_init(&b); buf_need(&b, s->len);
  for (size_t i = 0; i < s->len; i++) b.p[i] = (char)toupper((unsigned char)s->data[i]);
  b.n = s->len; return ret1(L, buf_finish(&b));
}
static int s_lower(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0); Buf b; buf_init(&b); buf_need(&b, s->len);
  for (size_t i = 0; i < s->len; i++) b.p[i] = (char)tolower((unsigned char)s->data[i]);
  b.n = s->len; return ret1(L, buf_finish(&b));
}
static int s_reverse(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0); Buf b; buf_init(&b); buf_need(&b, s->len);
  for (size_t i = 0; i < s->len; i++) b.p[i] = s->data[s->len - 1 - i];
  b.n = s->len; return ret1(L, buf_finish(&b));
}
static int s_rep(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0); lint cnt = arg_int(L, a, n, 1);
  Str *sep = n >= 3 && !isnil(a[2]) ? arg_str(L, a, n, 2) : NULL;
  size_t ls = s->len, lsep = sep ? sep->len : 0;
  if (cnt <= 0) return ret1(L, mkstr(str_new("", 0)));
  if ((ls + lsep) > 0 && (luint)cnt > (0x7fffffffULL / (ls + lsep))) lerror(L, "resulting string too large");
  size_t total = ls * (size_t)cnt + lsep * (size_t)(cnt - 1);
  if (total == 0) return ret1(L, mkstr(str_new("", 0)));
  char *buf = malloc(total + 1); if (!buf) lerror(L, "not enough memory");
  char *p = buf;
  for (lint i = 0; i < cnt; i++) {
    memcpy(p, s->data, ls); p += ls;
    if (sep && i < cnt - 1) { memcpy(p, sep->data, lsep); p += lsep; }
  }
  Value r = mkstr(str_new(buf, total)); free(buf);
  return ret1(L, r);
}
static int s_byte(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0);
  lint pi = arg_optint(L, a, n, 1, 1);
  size_t posi = posrelatI(pi, s->len), pose = getendpos(arg_optint(L, a, n, 2, pi), s->len);
  if (posi > pose) return 0;
  size_t cnt = pose - posi + 1;
  if (cnt >= 1000000) lerror(L, "string slice too long");
  ret_need(L, (int)cnt + 1);
  for (size_t i = 0; i < cnt; i++) L->ret[i] = mkint((unsigned char)s->data[posi + i - 1]);
  return (int)cnt;
}
static int s_char(State *L, Value *a, int n) {
  Buf b; buf_init(&b);
  for (int i = 0; i < n; i++) {
    lint c = arg_int(L, a, n, i);
    if ((luint)c > 255) { free(b.p); arg_error(L, i, "value out of range"); }
    buf_addc(&b, (char)c);
  }
  return ret1(L, buf_finish(&b));
}

/* ---------- pattern matching ---------- */
#define MAXCAPTURES 32
#define CAP_UNFINISHED (-1)
#define CAP_POSITION (-2)
#define MAXCCALLS 200
#define L_ESC '%'
#define SPECIALS "^$*+?.([%-"

typedef struct MatchState {
  const char *src_init, *src_end, *p_end; State *L; int matchdepth; int level;
  struct { const char *init; ptrdiff_t len; } capture[MAXCAPTURES];
} MatchState;

static const char *match(MatchState *ms, const char *s, const char *p);

static int check_capture(MatchState *ms, int l) {
  l -= '1';
  if (l < 0 || l >= ms->level || ms->capture[l].len == CAP_UNFINISHED) lerror(ms->L, "invalid capture index %%%d", l + 1);
  return l;
}
static int capture_to_close(MatchState *ms) {
  int level = ms->level;
  for (level--; level >= 0; level--) if (ms->capture[level].len == CAP_UNFINISHED) return level;
  lerror(ms->L, "invalid pattern capture");
}
static const char *class_end(MatchState *ms, const char *p) {
  switch (*p++) {
    case L_ESC:
      if (p == ms->p_end) lerror(ms->L, "malformed pattern (ends with '%%')");
      return p + 1;
    case '[':
      if (*p == '^') p++;
      do {
        if (p == ms->p_end) lerror(ms->L, "malformed pattern (missing ']')");
        if (*(p++) == L_ESC && p < ms->p_end) p++;
      } while (p >= ms->p_end || *p != ']');
      return p + 1;
    default: return p;
  }
}
static int match_class(int c, int cl) {
  int res;
  switch (tolower(cl)) {
    case 'a': res = isalpha(c); break; case 'c': res = iscntrl(c); break; case 'd': res = isdigit(c); break;
    case 'g': res = isgraph(c); break; case 'l': res = islower(c); break; case 'p': res = ispunct(c); break;
    case 's': res = isspace(c); break; case 'u': res = isupper(c); break; case 'w': res = isalnum(c); break;
    case 'x': res = isxdigit(c); break;
    default: return cl == c;
  }
  if (isupper(cl)) res = !res;
  return res;
}
static int matchbracketclass(int c, const char *p, const char *ec) {
  int sig = 1;
  if (*(p + 1) == '^') { sig = 0; p++; }
  while (++p < ec) {
    if (*p == L_ESC) { p++; if (match_class(c, (unsigned char)*p)) return sig; }
    else if (*(p + 1) == '-' && (p + 2 < ec)) { p += 2; if ((unsigned char)*(p - 2) <= c && c <= (unsigned char)*p) return sig; }
    else if ((unsigned char)*p == c) return sig;
  }
  return !sig;
}
static int singlematch(MatchState *ms, const char *s, const char *p, const char *ep) {
  if (s >= ms->src_end) return 0;
  int c = (unsigned char)*s;
  switch (*p) {
    case '.': return 1;
    case L_ESC: return match_class(c, (unsigned char)*(p + 1));
    case '[': return matchbracketclass(c, p, ep - 1);
    default: return (unsigned char)*p == c;
  }
}
static const char *matchbalance(MatchState *ms, const char *s, const char *p) {
  if (p >= ms->p_end - 1) lerror(ms->L, "malformed pattern (missing arguments to '%%b')");
  if (s >= ms->src_end || *s != *p) return NULL;
  int b = *p, e = *(p + 1), cont = 1;
  while (++s < ms->src_end) {
    if (*s == e) { if (--cont == 0) return s + 1; }
    else if (*s == b) cont++;
  }
  return NULL;
}
static const char *max_expand(MatchState *ms, const char *s, const char *p, const char *ep) {
  ptrdiff_t i = 0;
  while (singlematch(ms, s + i, p, ep)) i++;
  while (i >= 0) {
    const char *res = match(ms, s + i, ep + 1);
    if (res) return res;
    i--;
  }
  return NULL;
}
static const char *min_expand(MatchState *ms, const char *s, const char *p, const char *ep) {
  for (;;) {
    const char *res = match(ms, s, ep + 1);
    if (res != NULL) return res;
    else if (singlematch(ms, s, p, ep)) s++;
    else return NULL;
  }
}
static const char *start_capture(MatchState *ms, const char *s, const char *p, int what) {
  int level = ms->level;
  if (level >= MAXCAPTURES) lerror(ms->L, "too many captures");
  ms->capture[level].init = s; ms->capture[level].len = what; ms->level = level + 1;
  const char *res = match(ms, s, p);
  if (res == NULL) ms->level--;
  return res;
}
static const char *end_capture(MatchState *ms, const char *s, const char *p) {
  int l = capture_to_close(ms);
  ms->capture[l].len = s - ms->capture[l].init;
  const char *res = match(ms, s, p);
  if (res == NULL) ms->capture[l].len = CAP_UNFINISHED;
  return res;
}
static const char *match_capture(MatchState *ms, const char *s, int l) {
  l = check_capture(ms, l);
  size_t len = (size_t)ms->capture[l].len;
  if ((size_t)(ms->src_end - s) >= len && memcmp(ms->capture[l].init, s, len) == 0) return s + len;
  return NULL;
}
static const char *match(MatchState *ms, const char *s, const char *p) {
  if (ms->matchdepth-- == 0) lerror(ms->L, "pattern too complex");
  while (1) {
    if (p == ms->p_end) break;
    switch (*p) {
      case '(':
        if (*(p + 1) == ')') s = start_capture(ms, s, p + 2, CAP_POSITION);
        else s = start_capture(ms, s, p + 1, CAP_UNFINISHED);
        goto done;
      case ')': s = end_capture(ms, s, p + 1); goto done;
      case '$':
        if ((p + 1) != ms->p_end) goto dflt;
        s = (s == ms->src_end) ? s : NULL; goto done;
      case L_ESC:
        switch (*(p + 1)) {
          case 'b':
            s = matchbalance(ms, s, p + 2);
            if (s != NULL) { p += 4; continue; }
            goto done;
          case 'f': {
            p += 2;
            if (*p != '[') lerror(ms->L, "missing '[' after '%%f' in pattern");
            const char *ep = class_end(ms, p);
            char prev = (s == ms->src_init) ? '\0' : *(s - 1);
            if (!matchbracketclass((unsigned char)prev, p, ep - 1) &&
                matchbracketclass(s < ms->src_end ? (unsigned char)*s : 0, p, ep - 1)) { p = ep; continue; }
            s = NULL; goto done;
          }
          case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
            s = match_capture(ms, s, (unsigned char)*(p + 1));
            if (s != NULL) { p += 2; continue; }
            goto done;
          default: goto dflt;
        }
      default: dflt: {
        const char *ep = class_end(ms, p);
        if (!singlematch(ms, s, p, ep)) {
          if (ep < ms->p_end && (*ep == '*' || *ep == '?' || *ep == '-')) { p = ep + 1; continue; }
          s = NULL; goto done;
        }
        char epc = ep < ms->p_end ? *ep : '\0';
        switch (epc) {
          case '?': {
            const char *res = match(ms, s + 1, ep + 1);
            if (res != NULL) { s = res; goto done; }
            p = ep + 1; continue;
          }
          case '+': s++; /* fallthrough */
          case '*': s = max_expand(ms, s, p, ep); goto done;
          case '-': s = min_expand(ms, s, p, ep); goto done;
          default: s++; p = ep; continue;
        }
      }
    }
  }
done:
  ms->matchdepth++;
  return s;
}

static Value get_onecapture(MatchState *ms, int i, const char *s, const char *e) {
  if (i >= ms->level) {
    if (i != 0) lerror(ms->L, "invalid capture index %%%d", i + 1);
    return mkstr(str_new(s, (size_t)(e - s)));
  }
  ptrdiff_t l = ms->capture[i].len;
  if (l == CAP_UNFINISHED) lerror(ms->L, "unfinished capture");
  if (l == CAP_POSITION) return mkint((lint)(ms->capture[i].init - ms->src_init) + 1);
  return mkstr(str_new(ms->capture[i].init, (size_t)l));
}
static int push_captures(MatchState *ms, const char *s, const char *e, Value *out) {
  int nlevels = (ms->level == 0 && s) ? 1 : ms->level;
  for (int i = 0; i < nlevels; i++) out[i] = get_onecapture(ms, i, s, e);
  return nlevels;
}
static void prepstate(MatchState *ms, State *L, const char *s, size_t ls, const char *p, size_t lp) {
  ms->L = L; ms->matchdepth = MAXCCALLS; ms->src_init = s; ms->src_end = s + ls; ms->p_end = p + lp; ms->level = 0;
}
static int nospecials(const char *p, size_t l) {
  for (size_t i = 0; i < l; i++) if (strchr(SPECIALS, p[i]) && p[i] != '\0') return 0;
  return 1;
}
static const char *lmemfind(const char *s1, size_t l1, const char *s2, size_t l2) {
  if (l2 == 0) return s1;
  if (l2 > l1) return NULL;
  const char *init; l2--; l1 = l1 - l2;
  while (l1 > 0 && (init = memchr(s1, *s2, l1)) != NULL) {
    init++;
    if (memcmp(init, s2 + 1, l2) == 0) return init - 1;
    l1 -= (size_t)(init - s1); s1 = init;
  }
  return NULL;
}

static int str_find_aux(State *L, Value *a, int n, int find) {
  Str *s = arg_str(L, a, n, 0), *pat = arg_str(L, a, n, 1);
  size_t ls = s->len, lp = pat->len;
  size_t init = posrelatI(arg_optint(L, a, n, 2, 1), ls) - 1;
  if (init > ls) return ret1(L, NILV);
  if (find && ((n >= 4 && truthy(a[3])) || nospecials(pat->data, lp))) {
    const char *f = lmemfind(s->data + init, ls - init, pat->data, lp);
    if (f) { L->ret[0] = mkint((lint)(f - s->data) + 1); L->ret[1] = mkint((lint)(f - s->data) + (lint)lp); return 2; }
    return ret1(L, NILV);
  }
  MatchState ms; const char *p = pat->data;
  int anchor = (*p == '^');
  if (anchor) { p++; lp--; }
  const char *s1 = s->data + init;
  prepstate(&ms, L, s->data, ls, p, lp);
  do {
    const char *e;
    ms.level = 0; ms.matchdepth = MAXCCALLS;
    if ((e = match(&ms, s1, p)) != NULL) {
      if (find) {
        ret_need(L, MAXCAPTURES + 3);
        L->ret[0] = mkint((lint)(s1 - s->data) + 1); L->ret[1] = mkint((lint)(e - s->data));
        return push_captures(&ms, NULL, NULL, L->ret + 2) + 2;
      }
      ret_need(L, MAXCAPTURES + 2);
      return push_captures(&ms, s1, e, L->ret);
    }
  } while (s1++ < ms.src_end && !anchor);
  return ret1(L, NILV);
}
static int s_find(State *L, Value *a, int n) { return str_find_aux(L, a, n, 1); }
static int s_match(State *L, Value *a, int n) { return str_find_aux(L, a, n, 0); }

static int gmatch_aux(State *L, Value *a, int n) {
  CFn *self = L->ci->cf;
  Str *s = strof(self->up[0]), *pat = strof(self->up[1]);
  lint pos = self->up[2].u.i, last = self->up[3].u.i;
  MatchState ms;
  prepstate(&ms, L, s->data, s->len, pat->data, pat->len);
  for (const char *src = s->data + pos; src <= ms.src_end; src++) {
    ms.level = 0; ms.matchdepth = MAXCCALLS;
    const char *e = match(&ms, src, pat->data);
    if (e != NULL && (lint)(e - s->data) != last) {
      self->up[2] = mkint((lint)(e - s->data)); self->up[3] = mkint((lint)(e - s->data));
      ret_need(L, MAXCAPTURES + 2);
      return push_captures(&ms, src, e, L->ret);
    }
  }
  self->up[2] = mkint((lint)s->len + 1);
  return ret1(L, NILV);
}
static int s_gmatch(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0), *pat = arg_str(L, a, n, 1);
  size_t init = posrelatI(arg_optint(L, a, n, 2, 1), s->len) - 1;
  if (init > s->len) init = s->len + 1;
  CFn *c = cfn_new(gmatch_aux, "gmatch_iter", 4);
  c->up[0] = mkstr(s); c->up[1] = mkstr(pat); c->up[2] = mkint((lint)init); c->up[3] = mkint(-1);
  return ret1(L, mkobj(T_CFN, c));
}

static void add_s(MatchState *ms, Buf *b, const char *s, const char *e, Str *news) {
  const char *p = news->data, *end = p + news->len;
  while (p < end) {
    if (*p != L_ESC) { buf_addc(b, *p++); continue; }
    p++;
    if (p >= end) lerror(ms->L, "invalid use of '%%' in replacement string");
    if (*p == L_ESC) buf_addc(b, L_ESC);
    else if (isdigit((unsigned char)*p)) {
      if (*p != '0' && *p - '1' >= ms->level && *p != '1') lerror(ms->L, "invalid capture index %%%d in replacement string", *p - '0');
      Value v = *p == '0' ? mkstr(str_new(s, (size_t)(e - s))) : get_onecapture(ms, *p - '1', s, e);
      if (v.t != T_STR) v = tostring_basic(v);
      buf_add(b, strof(v)->data, strof(v)->len);
    } else lerror(ms->L, "invalid use of '%%' in replacement string");
    p++;
  }
}
static void add_value(MatchState *ms, Buf *b, const char *s, const char *e, Value repl) {
  State *L = ms->L; Value r;
  switch (repl.t) {
    case T_STR: case T_INT: case T_FLT: {
      Value rs = repl.t == T_STR ? repl : tostring_basic(repl);
      add_s(ms, b, s, e, strof(rs)); return;
    }
    case T_TABLE: {
      Value k = get_onecapture(ms, 0, s, e); int ok;
      r = index_val(L, repl, k, &ok); break;
    }
    default: {
      Value caps[MAXCAPTURES + 1];
      int nc = push_captures(ms, s, e, caps);
      r = call1(L, repl, caps, nc); break;
    }
  }
  if (!truthy(r)) { buf_add(b, s, (size_t)(e - s)); return; }
  if (r.t != T_STR && !isnum(r)) lerror(L, "invalid replacement value (a %s)", typename_of(r.t));
  if (r.t != T_STR) r = tostring_basic(r);
  buf_add(b, strof(r)->data, strof(r)->len);
}
static int s_gsub(State *L, Value *a, int n) {
  Str *s = arg_str(L, a, n, 0), *pat = arg_str(L, a, n, 1);
  Value repl = argv(a, n, 2);
  if (!(repl.t == T_STR || isnum(repl) || repl.t == T_TABLE || repl.t == T_LCL || repl.t == T_CFN))
    arg_typeerror(L, 2, "string/function/table", a, n);
  size_t srcl = s->len;
  lint max_s = arg_optint(L, a, n, 3, (lint)srcl + 1);
  const char *p = pat->data; size_t lp = pat->len;
  int anchor = (*p == '^');
  if (anchor) { p++; lp--; }
  MatchState ms; prepstate(&ms, L, s->data, srcl, p, lp);
  const char *src = s->data, *lastmatch = NULL;
  lint cnt = 0; Buf b; buf_init(&b);
  while (cnt < max_s) {
    ms.level = 0; ms.matchdepth = MAXCCALLS;
    const char *e = match(&ms, src, p);
    if (e != NULL && e != lastmatch) { cnt++; add_value(&ms, &b, src, e, repl); src = lastmatch = e; }
    else if (src < ms.src_end) buf_addc(&b, *src++);
    else break;
    if (anchor) break;
  }
  if (src < ms.src_end) buf_add(&b, src, (size_t)(ms.src_end - src));
  Value r = buf_finish(&b);
  L->ret[0] = r; L->ret[1] = mkint(cnt);
  return 2;
}

/* ---------- format ---------- */
static void addquoted(Buf *b, Str *s) {
  buf_addc(b, '"');
  for (size_t i = 0; i < s->len; i++) {
    unsigned char c = (unsigned char)s->data[i];
    if (c == '"' || c == '\\' || c == '\n') { buf_addc(b, '\\'); buf_addc(b, (char)c); }
    else if (iscntrl(c)) {
      char tmp[16];
      int l = (i + 1 < s->len && isdigit((unsigned char)s->data[i + 1])) ? snprintf(tmp, sizeof tmp, "\\%03d", c) : snprintf(tmp, sizeof tmp, "\\%d", c);
      buf_add(b, tmp, (size_t)l);
    } else buf_addc(b, (char)c);
  }
  buf_addc(b, '"');
}
static int s_format(State *L, Value *a, int n) {
  Str *fs = arg_str(L, a, n, 0);
  const char *f = fs->data, *fe = f + fs->len;
  Buf b; buf_init(&b);
  int arg = 0;
  while (f < fe) {
    if (*f != '%') { buf_addc(&b, *f++); continue; }
    f++;
    if (f >= fe) { free(b.p); lerror(L, "invalid conversion '%%' to 'format'"); }
    if (*f == '%') { buf_addc(&b, '%'); f++; continue; }
    char spec[32]; int sl = 0; spec[sl++] = '%';
    const char *st = f;
    while (f < fe && strchr("-+ #0", *f)) f++;
    int nd = 0; while (f < fe && isdigit((unsigned char)*f) && nd < 3) { f++; nd++; }
    if (f < fe && *f == '.') { f++; nd = 0; while (f < fe && isdigit((unsigned char)*f) && nd < 3) { f++; nd++; } }
    size_t speclen = (size_t)(f - st);
    char conv = f < fe ? *f : '\0';
    if (speclen > 20 || conv == '\0') { free(b.p); lerror(L, "invalid conversion '%%%.*s' to 'format'", (int)(speclen + (f < fe)), st); }
    memcpy(spec + 1, st, speclen); sl += (int)speclen; f++;
    /* width/precision limited to 2 digits */
    { const char *q = st; int run = 0; int bad = 0;
      while (q < f - 1 && strchr("-+ #0", *q)) q++;
      for (; q < f - 1; q++) { if (isdigit((unsigned char)*q)) { if (++run > 2) bad = 1; } else run = 0; }
      if (bad) { free(b.p); lerror(L, "invalid conversion '%%%.*s' to 'format'", (int)(f - st), st); } }
    arg++;
    if (conv != '%' && arg >= n && conv != '\0') { free(b.p); arg_error(L, arg, "no value"); }
    char out[600]; int ol;
    switch (conv) {
      case 'c': { spec[sl++] = 'c'; spec[sl] = 0; ol = snprintf(out, sizeof out, spec, (int)arg_int(L, a, n, arg)); buf_add(&b, out, (size_t)ol); break; }
      case 'd': case 'i': {
        lint v = arg_int(L, a, n, arg); spec[sl++] = 'l'; spec[sl++] = 'l'; spec[sl++] = 'd'; spec[sl] = 0;
        ol = snprintf(out, sizeof out, spec, (long long)v); buf_add(&b, out, (size_t)ol); break; }
      case 'u': case 'o': case 'x': case 'X': {
        lint v = arg_int(L, a, n, arg); spec[sl++] = 'l'; spec[sl++] = 'l'; spec[sl++] = conv; spec[sl] = 0;
        ol = snprintf(out, sizeof out, spec, (unsigned long long)v); buf_add(&b, out, (size_t)ol); break; }
      case 'a': case 'A': case 'e': case 'E': case 'f': case 'F': case 'g': case 'G': {
        lnum v = arg_num(L, a, n, arg); spec[sl++] = conv; spec[sl] = 0;
        ol = snprintf(out, sizeof out, spec, v); buf_add(&b, out, (size_t)ol); break; }
      case 'p': {
        Value v = a[arg]; spec[sl++] = 's'; spec[sl] = 0;
        char pb[64];
        if (v.t >= T_STR && v.t != T_BOX) snprintf(pb, sizeof pb, "%p", v.u.p); else strcpy(pb, "(null)");
        ol = snprintf(out, sizeof out, spec, pb); buf_add(&b, out, (size_t)ol); break; }
      case 'q': {
        if (speclen != 0) { free(b.p); lerror(L, "specifier '%%q' cannot have modifiers"); }
        Value v = a[arg];
        switch (v.t) {
          case T_STR: addquoted(&b, strof(v)); break;
          case T_INT:
            if (v.u.i == INT64_MIN) ol = snprintf(out, sizeof out, "0x%llx", (unsigned long long)v.u.i);
            else ol = snprintf(out, sizeof out, "%lld", (long long)v.u.i);
            buf_add(&b, out, (size_t)ol); break;
          case T_FLT:
            if (v.u.n == HUGE_VAL) ol = snprintf(out, sizeof out, "1e9999");
            else if (v.u.n == -HUGE_VAL) ol = snprintf(out, sizeof out, "-1e9999");
            else if (v.u.n != v.u.n) ol = snprintf(out, sizeof out, "(0/0)");
            else ol = snprintf(out, sizeof out, "%a", v.u.n);
            buf_add(&b, out, (size_t)ol); break;
          case T_NIL: case T_BOOL: { Value t = tostring_basic(v); buf_add(&b, strof(t)->data, strof(t)->len); break; }
          default: free(b.p); arg_error(L, arg, "value has no literal form");
        }
        break; }
      case 's': {
        Value sv = tostring_meta(L, a[arg]); a[arg] = sv; Str *ss = strof(sv);
        if (speclen == 0) { buf_add(&b, ss->data, ss->len); break; }
        if (memchr(ss->data, 0, ss->len)) { free(b.p); arg_error(L, arg, "string contains zeros"); }
        spec[sl++] = 's'; spec[sl] = 0;
        size_t need = ss->len + 200;
        char *tmp = malloc(need);
        ol = snprintf(tmp, need, spec, ss->data); buf_add(&b, tmp, (size_t)ol); free(tmp); break; }
      default:
        free(b.p);
        lerror(L, "invalid conversion '%%%.*s' to 'format'", (int)(f - st), st);
    }
  }
  return ret1(L, buf_finish(&b));
}

/* ---------- pack / unpack ---------- */
typedef enum { Kint, Kuint, Kfloat, Knumber, Kdouble, Kchar, Kstring, Kzstr, Kpadding, Kpaddalign, Knop } KOption;
typedef struct Header { State *L; int islittle; int maxalign; } Header;

static int getnum(const char **fmt, int df) {
  if (!isdigit((unsigned char)**fmt)) return df;
  int a = 0;
  do { a = a * 10 + (*((*fmt)++) - '0'); } while (isdigit((unsigned char)**fmt) && a <= (INT_MAX - 9) / 10);
  return a;
}
static int getnumlimit(Header *h, const char **fmt, int df) {
  int sz = getnum(fmt, df);
  if (sz > 16 || sz <= 0) lerror(h->L, "integral size (%d) out of limits [1,16]", sz);
  return sz;
}
static KOption getoption(Header *h, const char **fmt, int *size) {
  int opt = *((*fmt)++);
  *size = 0;
  switch (opt) {
    case 'b': *size = 1; return Kint; case 'B': *size = 1; return Kuint;
    case 'h': *size = 2; return Kint; case 'H': *size = 2; return Kuint;
    case 'l': *size = 8; return Kint; case 'L': *size = 8; return Kuint;
    case 'j': *size = 8; return Kint; case 'J': *size = 8; return Kuint;
    case 'T': *size = 8; return Kuint;
    case 'f': *size = 4; return Kfloat; case 'n': *size = 8; return Knumber; case 'd': *size = 8; return Kdouble;
    case 'i': *size = getnumlimit(h, fmt, 4); return Kint;
    case 'I': *size = getnumlimit(h, fmt, 4); return Kuint;
    case 's': *size = getnumlimit(h, fmt, 8); return Kstring;
    case 'c':
      *size = getnum(fmt, -1);
      if (*size == -1) lerror(h->L, "missing size for format option 'c'");
      return Kchar;
    case 'z': return Kzstr;
    case 'x': *size = 1; return Kpadding;
    case 'X': return Kpaddalign;
    case ' ': break;
    case '<': h->islittle = 1; break;
    case '>': h->islittle = 0; break;
    case '=': h->islittle = 1; break;
    case '!': h->maxalign = getnumlimit(h, fmt, 8); break;
    default: lerror(h->L, "invalid format option '%c'", opt);
  }
  return Knop;
}
static KOption getdetails(Header *h, size_t totalsize, const char **fmt, int *psize, int *ntoalign) {
  KOption opt = getoption(h, fmt, psize);
  int align = *psize;
  if (opt == Kpaddalign) {
    if (**fmt == '\0' || getoption(h, fmt, &align) == Kchar || align == 0)
      lerror(h->L, "bad argument #1 to '%s' (invalid next option for option 'X')", fn_display_name(h->L->ci->cf));
  }
  if (align <= 1 || opt == Kchar) *ntoalign = 0;
  else {
    if (align > h->maxalign) align = h->maxalign;
    if ((align & (align - 1)) != 0)
      lerror(h->L, "bad argument #1 to '%s' (format asks for alignment not power of 2)", fn_display_name(h->L->ci->cf));
    *ntoalign = (align - (int)(totalsize & (size_t)(align - 1))) & (align - 1);
  }
  return opt;
}
static void packint(Buf *b, luint n, int islittle, int size, int neg) {
  char buff[16];
  for (int i = 0; i < size; i++) {
    unsigned char byte = i < 8 ? (unsigned char)((n >> (i * 8)) & 0xff) : (neg ? 0xff : 0);
    buff[islittle ? i : size - 1 - i] = (char)byte;
  }
  buf_add(b, buff, (size_t)size);
}
static void copywithendian(char *dst, const char *src, int size, int islittle) {
  if (islittle) memcpy(dst, src, (size_t)size);
  else for (int i = 0; i < size; i++) dst[i] = src[size - 1 - i];
}
static int s_pack(State *L, Value *a, int n) {
  Header h = {L, 1, 1};
  const char *fmt = arg_str(L, a, n, 0)->data;
  Buf b; buf_init(&b);
  int arg = 0; size_t totalsize = 0;
  while (*fmt != '\0') {
    int size, ntoalign;
    KOption opt = getdetails(&h, totalsize, &fmt, &size, &ntoalign);
    totalsize += (size_t)ntoalign + (size_t)size;
    while (ntoalign-- > 0) buf_addc(&b, 0);
    arg++;
    switch (opt) {
      case Kint: {
        lint v = arg_int(L, a, n, arg);
        if (size < 8) { lint lim = (lint)1 << (size * 8 - 1); if (!(-lim <= v && v < lim)) { free(b.p); arg_error(L, arg, "integer overflow"); } }
        packint(&b, (luint)v, h.islittle, size, v < 0); break; }
      case Kuint: {
        lint v = arg_int(L, a, n, arg);
        if (size < 8 && !((luint)v < ((luint)1 << (size * 8)))) { free(b.p); arg_error(L, arg, "unsigned overflow"); }
        packint(&b, (luint)v, h.islittle, size, 0); break; }
      case Kfloat: { float f = (float)arg_num(L, a, n, arg); char tmp[4]; copywithendian(tmp, (char *)&f, 4, h.islittle); buf_add(&b, tmp, 4); break; }
      case Knumber: case Kdouble: { double d = arg_num(L, a, n, arg); char tmp[8]; copywithendian(tmp, (char *)&d, 8, h.islittle); buf_add(&b, tmp, 8); break; }
      case Kchar: {
        Str *s = arg_str(L, a, n, arg);
        if (s->len > (size_t)size) { free(b.p); arg_error(L, arg, "string longer than given size"); }
        buf_add(&b, s->data, s->len);
        for (size_t i = s->len; i < (size_t)size; i++) buf_addc(&b, 0);
        break; }
      case Kstring: {
        Str *s = arg_str(L, a, n, arg);
        if (size < 8 && s->len >= ((size_t)1 << (size * 8))) { free(b.p); arg_error(L, arg, "string length does not fit in given size"); }
        packint(&b, (luint)s->len, h.islittle, size, 0);
        buf_add(&b, s->data, s->len); totalsize += s->len; break; }
      case Kzstr: {
        Str *s = arg_str(L, a, n, arg);
        if (strlen(s->data) != s->len) { free(b.p); arg_error(L, arg, "string contains zeros"); }
        buf_add(&b, s->data, s->len); buf_addc(&b, 0); totalsize += s->len + 1; break; }
      case Kpadding: buf_addc(&b, 0); /* fallthrough */
      case Kpaddalign: case Knop: arg--; break;
    }
  }
  return ret1(L, buf_finish(&b));
}
static int s_packsize(State *L, Value *a, int n) {
  Header h = {L, 1, 1};
  const char *fmt = arg_str(L, a, n, 0)->data;
  size_t totalsize = 0;
  while (*fmt != '\0') {
    int size, ntoalign;
    KOption opt = getdetails(&h, totalsize, &fmt, &size, &ntoalign);
    if (opt == Kstring || opt == Kzstr) arg_error(L, 0, "variable-length format");
    size += ntoalign;
    if (totalsize > 0x7fffffffu - (size_t)size) arg_error(L, 0, "format result too large");
    totalsize += (size_t)size;
  }
  return ret1(L, mkint((lint)totalsize));
}
static lint unpackint(State *L, const char *str, int islittle, int size, int issigned) {
  luint res = 0;
  int limit = size <= 8 ? size : 8;
  for (int i = limit - 1; i >= 0; i--) { res <<= 8; res |= (unsigned char)str[islittle ? i : size - 1 - i]; }
  if (size < 8) {
    if (issigned) { luint mask = (luint)1 << (size * 8 - 1); res = (res ^ mask) - mask; }
  } else if (size > 8) {
    int mask = (!issigned || (lint)res >= 0) ? 0 : 0xff;
    for (int i = limit; i < size; i++)
      if ((unsigned char)str[islittle ? i : size - 1 - i] != mask) lerror(L, "%d-byte integer does not fit into Lua Integer", size);
  }
  return (lint)res;
}
static int s_unpack(State *L, Value *a, int n) {
  Header h = {L, 1, 1};
  const char *fmt = arg_str(L, a, n, 0)->data;
  Str *ds = arg_str(L, a, n, 1);
  const char *data = ds->data; size_t ld = ds->len;
  size_t pos = posrelatI(arg_optint(L, a, n, 2, 1), ld) - 1;
  if (pos > ld) arg_error(L, 2, "initial position out of string");
  int nres = 0;
  ret_need(L, 8);
  Value *tmp = NULL; int cap = 0;
  #define PUSH(v) do { if (nres >= cap) { cap = cap ? cap * 2 : 16; tmp = realloc(tmp, (size_t)cap * sizeof(Value)); } tmp[nres++] = (v); } while (0)
  while (*fmt != '\0') {
    int size, ntoalign;
    KOption opt = getdetails(&h, pos, &fmt, &size, &ntoalign);
    if ((size_t)ntoalign + (size_t)size > ld - pos) { free(tmp); arg_error(L, 1, "data string too short"); }
    pos += (size_t)ntoalign;
    switch (opt) {
      case Kint: case Kuint: PUSH(mkint(unpackint(L, data + pos, h.islittle, size, opt == Kint))); break;
      case Kfloat: { float f; char t[4]; copywithendian(t, data + pos, 4, h.islittle); memcpy(&f, t, 4); PUSH(mkflt((lnum)f)); break; }
      case Knumber: case Kdouble: { double d; char t[8]; copywithendian(t, data + pos, 8, h.islittle); memcpy(&d, t, 8); PUSH(mkflt(d)); break; }
      case Kchar: PUSH(mkstr(str_new(data + pos, (size_t)size))); break;
      case Kstring: {
        size_t len = (size_t)unpackint(L, data + pos, h.islittle, size, 0);
        if (len > ld - pos - (size_t)size) { free(tmp); arg_error(L, 1, "data string too short"); }
        PUSH(mkstr(str_new(data + pos + size, len))); pos += len; break; }
      case Kzstr: {
        size_t len = strnlen(data + pos, ld - pos);
        if (pos + len >= ld) { free(tmp); arg_error(L, 1, "unfinished string for format 'z'"); }
        PUSH(mkstr(str_new(data + pos, len))); pos += len + 1; break; }
      case Kpaddalign: case Kpadding: case Knop: break;
    }
    pos += (size_t)size;
  }
  PUSH(mkint((lint)pos + 1));
  ret_need(L, nres + 1);
  memcpy(L->ret, tmp, (size_t)nres * sizeof(Value)); free(tmp);
  return nres;
}

static int s_dump(State *L, Value *a, int n) {
  if (n < 1 || (a[0].t != T_LCL && a[0].t != T_CFN)) arg_typeerror(L, 0, "function", a, n);
  lerror(L, "unable to dump given function");
}

void open_string(State *L) {
  Table *t = reg_lib(L, "string");
  reg_func(t, "len", s_len); reg_func(t, "sub", s_sub); reg_func(t, "upper", s_upper); reg_func(t, "lower", s_lower);
  reg_func(t, "rep", s_rep); reg_func(t, "reverse", s_reverse); reg_func(t, "byte", s_byte); reg_func(t, "char", s_char);
  reg_func(t, "format", s_format); reg_func(t, "find", s_find); reg_func(t, "match", s_match);
  reg_func(t, "gmatch", s_gmatch); reg_func(t, "gsub", s_gsub);
  reg_func(t, "dump", s_dump); reg_func(t, "pack", s_pack); reg_func(t, "unpack", s_unpack); reg_func(t, "packsize", s_packsize);
  Table *mt = tab_new(0, 4);
  tab_setstr(L, mt, str_newz("__index"), mktab(t));
  G.strmeta = mt;
}
