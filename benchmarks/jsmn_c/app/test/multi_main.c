/* R1: JSMN_HEADER gives declarations only; implementation lives in one TU. */
#define JSMN_HEADER
#include "../jsmn.h"
#include <stdio.h>
#include <string.h>

extern int impl_count(const char *js);
extern int static_a_count(const char *js);
extern int static_b_count(const char *js);

int main(void) {
  jsmntok_t t[8];
  jsmn_parser p;
  int ok = 1;
  jsmn_init(&p);
  ok &= jsmn_parse(&p, "[1,2]", 5, t, 8) == 3;
  ok &= impl_count("{\"a\":[1,2]}") == 5;
  ok &= static_a_count("[1]") == 2;
  ok &= static_b_count("{}") == 1;
  puts(ok ? "multi-TU: ok" : "multi-TU: FAIL");
  return ok ? 0 : 1;
}
