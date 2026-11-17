# EMB-90: `jsmn`-compatible minimalistic JSON tokenizer in C (single header, no allocation)

Firmware teams need a tiny JSON tokenizer for microcontrollers: no dynamic memory, no libc beyond
`<stddef.h>`, C89-compatible, a single header `jsmn.h` (define `JSMN_HEADER` to get declarations only,
`JSMN_STATIC` to make functions static). It must be a drop-in replacement for the de-facto `jsmn` API:

```c
typedef enum { JSMN_UNDEFINED = 0, JSMN_OBJECT = 1 << 0, JSMN_ARRAY = 1 << 1,
               JSMN_STRING = 1 << 2, JSMN_PRIMITIVE = 1 << 3 } jsmntype_t;
enum jsmnerr { JSMN_ERROR_NOMEM = -1, JSMN_ERROR_INVAL = -2, JSMN_ERROR_PART = -3 };
typedef struct jsmntok { jsmntype_t type; int start; int end; int size;
#ifdef JSMN_PARENT_LINKS
  int parent;
#endif
} jsmntok_t;
typedef struct jsmn_parser { unsigned int pos; unsigned int toknext; int toksuper; } jsmn_parser;
void jsmn_init(jsmn_parser *parser);
int jsmn_parse(jsmn_parser *parser, const char *js, const size_t len, jsmntok_t *tokens, const unsigned int num_tokens);
```

Semantics:
* Tokens reference byte ranges `[start, end)` in the input (strings exclude the quotes); `size` is the
  number of direct children (object keys count as children of the object, and a key has size 1 when it
  has a value). Primitives are numbers, `true`, `false`, `null` (and, in non-strict mode, any other
  unquoted run of characters). Tokens are emitted in document order.
* `jsmn_parse` returns the number of tokens used, or a negative `jsmnerr`. With `tokens == NULL` it
  returns the number of tokens that *would* be needed (counting mode). Parsing is resumable: calling it
  again with the same parser and a longer buffer continues where it stopped (`JSMN_ERROR_PART` means
  more data is needed; `JSMN_ERROR_NOMEM` means more tokens are needed and the caller may grow the
  array and call again).
* String escapes `\" \/ \\ \b \f \r \n \t \uXXXX` are validated (not decoded); invalid escapes or
  unterminated structures are errors. Unmatched closing brackets are `JSMN_ERROR_INVAL`.
* `JSMN_STRICT` mode: primitives must be valid JSON literals/numbers and may not be object keys, and
  primitives must be followed by a delimiter. `JSMN_PARENT_LINKS` mode records `parent` (index or -1),
  which also makes closing-bracket matching O(1) per level.

Deliverables: `jsmn.h`, a `Makefile` with `test` building the test-suite in all four configurations
(default, `-DJSMN_STRICT=1`, `-DJSMN_PARENT_LINKS=1`, both), a test-suite, two examples (`simple.c`
extracting fields from a JSON object, and `jsondump.c` that pretty-prints JSON read from stdin by growing
the token array on `JSMN_ERROR_NOMEM`), and a README.
