# jsmn.h — tiny JSON tokenizer for microcontrollers

A single-header, allocation-free, C89, libc-free (`<stddef.h>` only) JSON tokenizer
with the de-facto `jsmn` API. It does not build a tree or decode anything: it fills a
caller-provided array of tokens pointing at `[start, end)` byte ranges in your input.

## Install / use

Copy `jsmn.h` into your project.

```c
#include "jsmn.h"                 /* in exactly one .c file: declarations + implementation */
/* other files:  #define JSMN_HEADER  before including -> declarations only          */
/* single file:  #define JSMN_STATIC  before including -> all functions are static   */

jsmn_parser p;
jsmntok_t t[64];
jsmn_init(&p);
int r = jsmn_parse(&p, js, len, t, 64);   /* tokens used, or negative error */
```

## API

| item | meaning |
|---|---|
| `jsmn_init(p)` | `pos=0, toknext=0, toksuper=-1` |
| `jsmn_parse(p, js, len, tokens, num_tokens)` | returns number of tokens, or `JSMN_ERROR_NOMEM` (-1, need more tokens), `JSMN_ERROR_INVAL` (-2, invalid input), `JSMN_ERROR_PART` (-3, input incomplete) |
| `jsmn_parse(p, js, len, NULL, 0)` | counting mode: returns the number of tokens needed |

Token: `type` (`JSMN_OBJECT|ARRAY|STRING|PRIMITIVE`), `start`, `end` (exclusive; strings exclude the quotes),
`size` (direct children; an object key has size 1 when it has a value; an object's size is its number of keys),
and, with `JSMN_PARENT_LINKS`, `parent` (index, or -1 for top-level tokens; the parent of a value is its key token).
Tokens are emitted in document order, so a subtree is a contiguous run.

### Resumable parsing
Call `jsmn_parse` again with the **same parser** after
* `JSMN_ERROR_PART`: pass the same buffer, longer `len` (parsing resumes at the unfinished token);
* `JSMN_ERROR_NOMEM`: pass a larger token array (existing tokens must be kept, e.g. `realloc`).

### Compile-time options
* `JSMN_STRICT` — primitives must be valid JSON numbers/`true`/`false`/`null` and be followed by a delimiter
  (a top-level primitive at the very end of input yields `PART`); primitives and containers cannot be object keys;
  commas/colons/values must be in valid positions (no trailing/missing commas, missing colons); raw control
  characters in strings are rejected.
* `JSMN_PARENT_LINKS` — adds `parent`; closing brackets are matched in O(1) instead of scanning back (O(n) per closer).
* `JSMN_HEADER`, `JSMN_STATIC` — see above.

### Behaviour notes
* String escapes `\" \/ \\ \b \f \r \n \t \uXXXX` are validated, not decoded. Bad escape/hex → `INVAL`; truncated → `PART`.
* Unterminated string/object/array → `PART`. Unmatched or mismatched closing bracket → `INVAL`.
* Several top-level values are tokenised one after another.
* Non-strict mode is lenient: any unquoted run of characters (no control chars) is a primitive, also as object key.
* Counting mode has no token storage, so it validates strings, primitives and bracket balance only; it does not
  check bracket *types* or (strict) comma/colon placement. If a real parse succeeds, the counts agree.
* Not thread-safe per parser; no global state.

## Build, test, run

```sh
make test       # builds & runs tests/test.c in 4 configs (default, STRICT, PARENT_LINKS, both),
                # the JSMN_STATIC test and the example smoke tests. Needs only make and a C compiler.
make examples   # build/simple, build/jsondump
make sanitize   # optional: all configs under ASan/UBSan
make clean
echo '{"a":[1,2]}' | build/jsondump
build/simple
```
Everything is compiled with `-std=c89 -pedantic -Wall -Wextra -Werror`.

## Layout
* `jsmn.h` — the library. `tests/` — test-suite (names carry requirement ids), `examples/simple.c` (field
  extraction), `examples/jsondump.c` (stdin pretty printer, grows the token array on `NOMEM`).

## Design
A single pass state machine. `toksuper` is the index of the token currently receiving children (a container, or
an object key after `:`). Strings and primitives are only committed once complete, so a failed call leaves the
parser at the start of the unfinished token and can simply be repeated. In strict mode, token placement is validated
by looking at the previous non-whitespace character together with the kind of `toksuper`.
