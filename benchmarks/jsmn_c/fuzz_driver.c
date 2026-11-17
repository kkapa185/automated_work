#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "jsmn.h"
/* Reads NUL-separated JSON snippets from stdin; prints the token stream (or error) for each. */
int main(void) {
  static char buf[1 << 20];
  size_t n = fread(buf, 1, sizeof(buf) - 1, stdin), i = 0;
  buf[n] = 0;
  while (i < n) {
    size_t len = strlen(buf + i);
    jsmn_parser p; jsmntok_t t[64]; int r, k;
    jsmn_init(&p);
    r = jsmn_parse(&p, buf + i, len, t, 64);
    printf("%d", r);
    for (k = 0; k < r; k++) {
      printf(" [%d %d %d %d", t[k].type, t[k].start, t[k].end, t[k].size);
#ifdef JSMN_PARENT_LINKS
      printf(" %d", t[k].parent);
#endif
      printf("]");
    }
    jsmn_init(&p);
    printf(" count=%d\n", jsmn_parse(&p, buf + i, len, NULL, 0));
    i += len + 1;
  }
  return 0;
}
