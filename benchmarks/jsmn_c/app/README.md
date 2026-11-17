# jsmn.h — tiny allocation-free JSON tokenizer (C89)

A single-header, `jsmn`-API-compatible JSON tokenizer for microcontrollers: no dynamic memory, no libc
beyond `<stddef.h>`, C89. It splits JSON into tokens that reference byte ranges of the input; it does not
decode or fully validate JSON.

## Use

```c
#include "jsmn.h"
jsmn_parser p; jsmntok_t t[128];
jsmn_init(&p);
int r = jsmn_parse(&p, js, strlen(js), t, 128);   /* tokens used, or a negative jsmnerr */
```

* `JSMN_HEADER` — declarations only (include this way from all but one translation unit).
* `JSMN_STATIC` — all functions `static` (header-only use in one TU).
* `JSMN_STRICT` — lexical strictness (below). `JSMN_PARENT_LINKS` — adds `int parent` to `jsmntok_t`
  (index of the enclosing token, `-1` for root) and makes closing-bracket matching O(1) per level.

Types: `jsmntype_t` (`JSMN_UNDEFINED=0, OBJECT=1, ARRAY=2, STRING=4, PRIMITIVE=8`), `jsmnerr`
(`NOMEM=-1, INVAL=-2, PART=-3`), `jsmntok_t {type,start,end,size[,parent]}`,
`jsmn_parser {pos,toknext,toksuper}`.

## Semantics

* Tokens cover `[start,end)`; strings exclude the quotes; containers span opener..closer. Document order.
  `size` = number of direct children (object keys are children of the object; a key has size 1 once it has a value).
* Primitives: numbers, `true`, `false`, `null` and (non-strict) any other unquoted run of printable characters.
* `tokens == NULL` is counting mode: returns the number of tokens needed. It is a fast scan that skips every
  check needing the token array (closer/opener matching, unclosed containers at end, key/value bookkeeping),
  so e.g. `{"a":"b"` returns 3 and `[}` returns 1. Character-level errors (bad escapes, illegal characters,
  strict-mode lexical checks) are still reported. Counting mode does not modify `toknext`.
* Resumable: call again with the same parser and a longer buffer. `JSMN_ERROR_PART` = more data needed (an
  unterminated string or unclosed container/strict primitive); `JSMN_ERROR_NOMEM` = grow the token array (keep
  its content) and call again.
* Escapes `\" \/ \\ \b \f \r \n \t \uXXXX` are validated, not decoded; others are `JSMN_ERROR_INVAL`.
  Unmatched/mismatched closing brackets are `JSMN_ERROR_INVAL`.
* Strict mode: a primitive must start with `-`, a digit, `t`, `f` or `n` (else `INVAL`) but its spelling is not
  checked (`tru`, `01`, `-` pass); it ends at whitespace, `,`, `]` or `}` (`:` does not end it); a primitive
  reaching end of input gives `PART`; objects, arrays and primitives cannot be object keys.
* Input is processed up to `len` bytes or the first NUL byte, whichever comes first.

## Build, test, run

```
make test      # test-suite in 4 configs (default, STRICT, PARENT_LINKS, both) + multi-TU + examples
make all       # build examples into build/   (build/simple, build/jsondump)
build/jsondump < example/sample.json
make clean
```
All code compiles with `-std=c89 -pedantic -Wall -Wextra -Werror`. No external dependencies.

Examples: `example/simple.c` extracts fields of an object; `example/jsondump.c` pretty-prints stdin and doubles
its token array (realloc) on `JSMN_ERROR_NOMEM`.

## Design

`jsmn_parse` is a single-pass state machine. `toksuper` is the token that receives new children. `:` makes the
last token (the key) the super token, `,` returns to the enclosing container. Closing brackets find the
innermost open token (`end == -1`), by walking `parent` links or scanning backwards. Failed string/primitive
scans restore `pos` to the token start so the call can be resumed.
