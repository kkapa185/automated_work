/* Extract fields from a JSON object. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../jsmn.h"

static const char *JSON_STRING =
    "{\"user\": \"johndoe\", \"admin\": false, \"uid\": 1000,\n  "
    "\"groups\": [\"users\", \"wheel\", \"audio\", \"video\"]}";

static int jsoneq(const char *json, const jsmntok_t *tok, const char *s) {
  if (tok->type == JSMN_STRING && (int)strlen(s) == tok->end - tok->start &&
      strncmp(json + tok->start, s, (size_t)(tok->end - tok->start)) == 0) {
    return 0;
  }
  return -1;
}

int main(void) {
  int i, r;
  jsmn_parser p;
  jsmntok_t t[128];

  jsmn_init(&p);
  r = jsmn_parse(&p, JSON_STRING, strlen(JSON_STRING), t,
                 (unsigned int)(sizeof(t) / sizeof(t[0])));
  if (r < 0) {
    printf("Failed to parse JSON: %d\n", r);
    return 1;
  }
  if (r < 1 || t[0].type != JSMN_OBJECT) {
    printf("Object expected\n");
    return 1;
  }

  for (i = 1; i < r; i++) {
    if (jsoneq(JSON_STRING, &t[i], "user") == 0) {
      printf("- User: %.*s\n", t[i + 1].end - t[i + 1].start,
             JSON_STRING + t[i + 1].start);
      i++;
    } else if (jsoneq(JSON_STRING, &t[i], "admin") == 0) {
      printf("- Admin: %.*s\n", t[i + 1].end - t[i + 1].start,
             JSON_STRING + t[i + 1].start);
      i++;
    } else if (jsoneq(JSON_STRING, &t[i], "uid") == 0) {
      printf("- UID: %.*s\n", t[i + 1].end - t[i + 1].start,
             JSON_STRING + t[i + 1].start);
      i++;
    } else if (jsoneq(JSON_STRING, &t[i], "groups") == 0) {
      int j;
      printf("- Groups:\n");
      if (t[i + 1].type != JSMN_ARRAY) {
        continue;
      }
      for (j = 0; j < t[i + 1].size; j++) {
        const jsmntok_t *g = &t[i + j + 2];
        printf("  * %.*s\n", g->end - g->start, JSON_STRING + g->start);
      }
      i += t[i + 1].size + 1;
    } else {
      printf("Unexpected key: %.*s\n", t[i].end - t[i].start,
             JSON_STRING + t[i].start);
    }
  }
  return 0;
}
