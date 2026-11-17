#include "../jsmn.h"
#include <string.h>
int impl_count(const char *js) {
  jsmn_parser p;
  jsmn_init(&p);
  return jsmn_parse(&p, js, strlen(js), NULL, 0);
}
