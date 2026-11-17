/* Pretty-print JSON read from stdin. The token array grows on
 * JSMN_ERROR_NOMEM and parsing resumes with the same parser. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "jsmn.h"

static void indent(int depth) {
  int i;
  for (i = 0; i < depth; i++) {
    fputs("  ", stdout);
  }
}

/* Prints the value starting at token i; returns the index after it. */
static int dump(const char *js, const jsmntok_t *t, int i, int depth) {
  int n, j;
  switch (t[i].type) {
  case JSMN_STRING:
    printf("\"%.*s\"", t[i].end - t[i].start, js + t[i].start);
    return i + 1;
  case JSMN_PRIMITIVE:
    printf("%.*s", t[i].end - t[i].start, js + t[i].start);
    return i + 1;
  case JSMN_ARRAY:
    n = t[i].size;
    i++;
    if (n == 0) {
      fputs("[]", stdout);
      return i;
    }
    fputs("[\n", stdout);
    for (j = 0; j < n; j++) {
      indent(depth + 1);
      i = dump(js, t, i, depth + 1);
      fputs(j + 1 < n ? ",\n" : "\n", stdout);
    }
    indent(depth);
    fputs("]", stdout);
    return i;
  case JSMN_OBJECT:
    n = t[i].size;
    i++;
    if (n == 0) {
      fputs("{}", stdout);
      return i;
    }
    fputs("{\n", stdout);
    for (j = 0; j < n; j++) {
      int has_value;
      indent(depth + 1);
      has_value = t[i].size > 0;
      i = dump(js, t, i, depth + 1);
      if (has_value) {
        fputs(": ", stdout);
        i = dump(js, t, i, depth + 1);
      }
      fputs(j + 1 < n ? ",\n" : "\n", stdout);
    }
    indent(depth);
    fputs("}", stdout);
    return i;
  default:
    return i + 1;
  }
}

int main(void) {
  char *js = NULL;
  size_t len = 0, cap = 0, got;
  jsmntok_t *tokens;
  unsigned int ntok = 16;
  jsmn_parser p;
  int r, i;

  for (;;) {
    if (cap - len < 4096) {
      char *nb;
      cap = cap ? cap * 2 : 8192;
      nb = (char *)realloc(js, cap);
      if (nb == NULL) {
        fprintf(stderr, "out of memory\n");
        return 1;
      }
      js = nb;
    }
    got = fread(js + len, 1, cap - len, stdin);
    if (got == 0) {
      break;
    }
    len += got;
  }

  tokens = (jsmntok_t *)malloc(sizeof(*tokens) * ntok);
  if (tokens == NULL) {
    fprintf(stderr, "out of memory\n");
    return 1;
  }
  jsmn_init(&p);
  for (;;) {
    jsmntok_t *nt;
    r = jsmn_parse(&p, js ? js : "", len, tokens, ntok);
    if (r != JSMN_ERROR_NOMEM) {
      break;
    }
    ntok *= 2;
    nt = (jsmntok_t *)realloc(tokens, sizeof(*tokens) * ntok);
    if (nt == NULL) {
      fprintf(stderr, "out of memory\n");
      return 1;
    }
    tokens = nt;
  }
  if (r == JSMN_ERROR_INVAL) {
    fprintf(stderr, "invalid JSON\n");
    return 1;
  }
  if (r == JSMN_ERROR_PART) {
    fprintf(stderr, "incomplete JSON\n");
    return 1;
  }
  i = 0;
  while (i < r) {
    i = dump(js, tokens, i, 0);
    putchar('\n');
  }
  free(tokens);
  free(js);
  return 0;
}
