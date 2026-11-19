/* os library */
#include "lua.h"
#include <time.h>
#include <errno.h>
#include <limits.h>
#include <unistd.h>
#include <sys/wait.h>

static int os_pusherr(State *L, const char *fname) {
  int en = errno;
  L->ret[0] = NILV;
  L->ret[1] = mkstr(fname ? str_fmt("%s: %s", fname, strerror(en)) : str_newz(strerror(en)));
  L->ret[2] = mkint(en);
  return 3;
}
static int os_clock(State *L, Value *a, int n) { return ret1(L, mkflt((lnum)clock() / (lnum)CLOCKS_PER_SEC)); }
static int os_difftime(State *L, Value *a, int n) { return ret1(L, mkflt(arg_num(L, a, n, 0) - arg_optnum(L, a, n, 1, 0))); }
static int os_getenv(State *L, Value *a, int n) {
  const char *v = getenv(arg_str(L, a, n, 0)->data);
  return ret1(L, v ? mkstr(str_newz(v)) : NILV);
}
static int os_execute(State *L, Value *a, int n) {
  const char *cmd = n >= 1 && !isnil(a[0]) ? arg_str(L, a, n, 0)->data : NULL;
  fflush(NULL);
  errno = 0;
  int st = system(cmd);
  if (cmd == NULL) return ret1(L, mkbool(st != 0));
  if (st == -1) return os_pusherr(L, NULL);
  const char *what = "exit"; int code = st;
  if (WIFEXITED(st)) code = WEXITSTATUS(st); else if (WIFSIGNALED(st)) { what = "signal"; code = WTERMSIG(st); }
  L->ret[0] = (what[0] == 'e' && code == 0) ? mkbool(1) : NILV;
  L->ret[1] = mkstr(str_newz(what)); L->ret[2] = mkint(code);
  return 3;
}
static int os_exit(State *L, Value *a, int n) {
  int status = 0;
  if (n >= 1 && a[0].t == T_BOOL) status = a[0].u.b ? 0 : 1;
  else if (n >= 1 && !isnil(a[0])) status = (int)arg_int(L, a, n, 0);
  fflush(stdout); fflush(stderr);
  exit(status);
}
static int os_remove(State *L, Value *a, int n) {
  const char *f = arg_str(L, a, n, 0)->data;
  if (remove(f) == 0) return ret1(L, mkbool(1));
  return os_pusherr(L, f);
}
static int os_rename(State *L, Value *a, int n) {
  const char *f = arg_str(L, a, n, 0)->data, *t = arg_str(L, a, n, 1)->data;
  if (rename(f, t) == 0) return ret1(L, mkbool(1));
  return os_pusherr(L, f);
}
static int os_tmpname(State *L, Value *a, int n) {
  char buf[] = "/tmp/lua_XXXXXX";
  int fd = mkstemp(buf);
  if (fd == -1) lerror(L, "unable to generate a unique filename");
  close(fd);
  return ret1(L, mkstr(str_newz(buf)));
}
static int os_setlocale(State *L, Value *a, int n) {
  const char *l = n >= 1 && !isnil(a[0]) ? arg_str(L, a, n, 0)->data : NULL;
  if (!l || !*l || !strcmp(l, "C") || !strcmp(l, "POSIX")) return ret1(L, mkstr(str_newz("C")));
  return ret1(L, NILV);
}

static void setfield(State *L, Table *t, const char *k, int v) { tab_setstr(L, t, str_newz(k), mkint(v)); }
static void setallfields(State *L, Table *t, struct tm *tm) {
  setfield(L, t, "year", tm->tm_year + 1900); setfield(L, t, "month", tm->tm_mon + 1); setfield(L, t, "day", tm->tm_mday);
  setfield(L, t, "hour", tm->tm_hour); setfield(L, t, "min", tm->tm_min); setfield(L, t, "sec", tm->tm_sec);
  setfield(L, t, "yday", tm->tm_yday + 1); setfield(L, t, "wday", tm->tm_wday + 1);
  tab_setstr(L, t, str_newz("isdst"), mkbool(tm->tm_isdst > 0));
}
static int getfield(State *L, Table *t, const char *k, int d, int delta) {
  Value v = tab_getstr(t, str_newz(k));
  lint res;
  if (isnil(v)) {
    if (d < 0) lerror(L, "field '%s' missing in date table", k);
    return d;
  }
  if (!tointeger_v(v, &res)) {
    if (isnum(v) || v.t == T_STR) lerror(L, "field '%s' is not an integer", k);
    lerror(L, "field '%s' missing in date table", k);
  }
  if (!(res >= 0 ? res - delta <= INT_MAX : INT_MIN + delta <= res)) lerror(L, "field '%s' is out-of-bound", k);
  return (int)(res - delta);
}
static int os_time(State *L, Value *a, int n) {
  if (n < 1 || isnil(a[0])) return ret1(L, mkint((lint)time(NULL)));
  Table *t = arg_table(L, a, n, 0);
  struct tm tm; memset(&tm, 0, sizeof tm);
  tm.tm_year = getfield(L, t, "year", -1, 1900); tm.tm_mon = getfield(L, t, "month", -1, 1);
  tm.tm_mday = getfield(L, t, "day", -1, 0); tm.tm_hour = getfield(L, t, "hour", 12, 0);
  tm.tm_min = getfield(L, t, "min", 0, 0); tm.tm_sec = getfield(L, t, "sec", 0, 0);
  Value dst = tab_getstr(t, str_newz("isdst"));
  tm.tm_isdst = isnil(dst) ? -1 : truthy(dst);
  time_t r = mktime(&tm);
  if (r == (time_t)-1) lerror(L, "time result cannot be represented in this installation");
  setallfields(L, t, &tm);
  return ret1(L, mkint((lint)r));
}
static const char *const LUA_STRFTIMEOPTIONS[] = {
  "aAbBcCdDeFgGhHIjmMnprRStTuUVwWxXyYzZ%", "||", "EcECExEXEyEY", "OdOeOHOIOmOMOSOuOUOVOwOWOy" };
static const char *checkoption(State *L, const char *conv, ptrdiff_t convlen, char *buff) {
  const char *option = LUA_STRFTIMEOPTIONS[0]; int oplen = 1;
  for (; *option != '\0' && oplen <= convlen; option += oplen) {
    if (*option == '|') oplen++;
    else if (memcmp(conv, option, (size_t)oplen) == 0) { memcpy(buff, conv, (size_t)oplen); buff[oplen] = '\0'; return conv + oplen; }
  }
  char m[64]; snprintf(m, sizeof m, "invalid conversion specifier '%%%s'", conv);
  arg_error(L, 0, m);
}
static int os_date(State *L, Value *a, int n) {
  Str *fs = n >= 1 && !isnil(a[0]) ? arg_str(L, a, n, 0) : str_newz("%c");
  time_t t = n >= 2 && !isnil(a[1]) ? (time_t)arg_int(L, a, n, 1) : time(NULL);
  const char *s = fs->data, *se = s + fs->len;
  struct tm tmr, *stm;
  if (*s == '!') { stm = gmtime_r(&t, &tmr); s++; } else stm = localtime_r(&t, &tmr);
  if (stm == NULL) lerror(L, "date result cannot be represented in this installation");
  if (strcmp(s, "*t") == 0) {
    Table *tb = tab_new(0, 9);
    setallfields(L, tb, stm);
    return ret1(L, mktab(tb));
  }
  LBuf b; lbuf_init(&b);
  char cc[4]; cc[0] = '%';
  while (s < se) {
    if (*s != '%') { lbuf_addc(&b, *s++); continue; }
    s = checkoption(L, s + 1, se - (s + 1), cc + 1);
    char buff[250];
    size_t rl = strftime(buff, sizeof buff, cc, stm);
    lbuf_add(&b, buff, rl);
  }
  return ret1(L, lbuf_finish(&b));
}

void open_os(State *L) {
  Table *t = reg_lib(L, "os");
  reg_func(t, "clock", os_clock); reg_func(t, "date", os_date); reg_func(t, "difftime", os_difftime);
  reg_func(t, "exit", os_exit); reg_func(t, "execute", os_execute); reg_func(t, "getenv", os_getenv); reg_func(t, "remove", os_remove);
  reg_func(t, "rename", os_rename); reg_func(t, "setlocale", os_setlocale); reg_func(t, "time", os_time);
  reg_func(t, "tmpname", os_tmpname);
}
