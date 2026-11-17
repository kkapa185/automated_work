/* Pretty-print JSON read from stdin; grows the token array on NOMEM. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../jsmn.h"

static void indent(int n) {
  while (n-- > 0) fputs("  ", stdout);
}

/* prints token i (and its subtree); returns index of the next token */
static int dump(const char *js, const jsmntok_t *t, int i, int level) {
  int j, n = t[i].size;

  if (t[i].type == JSMN_OBJECT || t[i].type == JSMN_ARRAY) {
    int is_obj = t[i].type == JSMN_OBJECT;
    char open = is_obj ? '{' : '[';
    char close = is_obj ? '}' : ']';
    int next = i + 1;
    if (n == 0) {
      printf("%c%c", open, close);
      return next;
    }
    printf("%c\n", open);
    for (j = 0; j < n; j++) {
      indent(level + 1);
      if (is_obj) {
        printf("\"%.*s\": ", t[next].end - t[next].start, js + t[next].start);
        next++;
      }
      next = dump(js, t, next, level + 1);
      puts(j + 1 < n ? "," : "");
    }
    indent(level);
    printf("%c", close);
    return next;
  }
  if (t[i].type == JSMN_STRING) {
    printf("\"%.*s\"", t[i].end - t[i].start, js + t[i].start);
  } else {
    printf("%.*s", t[i].end - t[i].start, js + t[i].start);
  }
  return i + 1;
}

int main(void) {
  size_t cap = 4096, len = 0, got;
  char *js = (char *)malloc(cap);
  unsigned int ntok = 16;
  jsmntok_t *tok = (jsmntok_t *)malloc(sizeof(*tok) * ntok);
  jsmn_parser p;
  int r;

  if (!js || !tok) return 2;
  while ((got = fread(js + len, 1, cap - len, stdin)) > 0) {
    len += got;
    if (len == cap) {
      char *n = (char *)realloc(js, cap * 2);
      if (!n) return 2;
      js = n;
      cap *= 2;
    }
  }

  jsmn_init(&p);
  for (;;) {
    r = jsmn_parse(&p, js, len, tok, ntok);
    if (r == JSMN_ERROR_NOMEM) {
      jsmntok_t *n;
      ntok *= 2;
      n = (jsmntok_t *)realloc(tok, sizeof(*tok) * ntok);
      if (!n) return 2;
      tok = n;
      continue; /* parser state is kept: resume */
    }
    break;
  }
  if (r < 0) {
    fprintf(stderr, "parse error: %d\n", r);
    return 1;
  }
  if (r > 0) {
    dump(js, tok, 0, 0);
    putchar('\n');
  }
  free(tok);
  free(js);
  return 0;
}
