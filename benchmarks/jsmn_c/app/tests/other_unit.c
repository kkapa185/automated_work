/* Second translation unit: uses jsmn.h in declaration-only mode (R1). */
#define JSMN_HEADER
#include "jsmn.h"
#include <string.h>

int other_unit_count(const char *js) {
  jsmn_parser p;
  jsmn_init(&p);
  return jsmn_parse(&p, js, strlen(js), NULL, 0);
}
