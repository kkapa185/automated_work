/* R1: JSMN_STATIC copies of the library in two TUs must not clash. */
#define JSMN_STATIC
#include "../jsmn.h"
#include <string.h>
int static_a_count(const char *js) {
  jsmn_parser p;
  jsmn_init(&p);
  return jsmn_parse(&p, js, strlen(js), NULL, 0);
}
