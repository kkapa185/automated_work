/* R1: JSMN_STATIC single-file use. */
#define JSMN_STATIC
#include "jsmn.h"
#include <stdio.h>
#include <string.h>

int main(void) {
  jsmn_parser p;
  jsmntok_t t[8];
  const char *js = "{\"a\":[1,2]}";
  int r;
  jsmn_init(&p);
  r = jsmn_parse(&p, js, strlen(js), t, 8);
  if (r != 5 || t[2].type != JSMN_ARRAY) {
    printf("static_test FAIL (%d)\n", r);
    return 1;
  }
  printf("static_test ok\n");
  return 0;
}
