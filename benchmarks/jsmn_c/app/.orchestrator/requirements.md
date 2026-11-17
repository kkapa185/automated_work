# EMB-90 requirements: jsmn-compatible JSON tokenizer

## Product
A single-header, allocation-free, C89, libc-free (only `<stddef.h>`) JSON tokenizer `jsmn.h`
API-compatible with the de-facto `jsmn` library, plus a Makefile (`make test` over four
configurations), a C test-suite, two examples (`simple.c`, `jsondump.c`) and a README.
Classification: C library. Test strategy: C test program compiled 4 ways, plus example smoke tests.

## Acceptance criteria
R1. `jsmn.h` is a single header; `JSMN_HEADER` yields declarations only; `JSMN_STATIC` makes functions static (`JSMN_API`).
R2. Types/enums/struct layouts exactly as in the task (jsmntype_t values 0,1,2,4,8; errors -1,-2,-3; `parent` field only with `JSMN_PARENT_LINKS`; parser = pos,toknext,toksuper).
R3. Includes only `<stddef.h>`; compiles clean under `-std=c89 -pedantic -Wall -Wextra` (no `//` comments, no mixed decls).
R4. `jsmn_init` sets pos=0,toknext=0,toksuper=-1.
R5. Tokens have `[start,end)` byte ranges; string ranges exclude quotes; emitted in document order.
R6. `size` = direct children; object key has size 1 with value; object size counts keys (and values nested under keys, not double counted); array size counts elements.
R7. Primitives: numbers, true, false, null; non-strict accepts any unquoted run ending at delimiter (`\t \r \n space , ] }` ; also `:` in non-strict).
R8. Return value = tokens used; `tokens==NULL` counting mode returns required count without writing, and agrees with a real parse.
R9. Resumability: after `JSMN_ERROR_PART` (truncated input) calling again with same parser and longer input continues and yields the same result as a one-shot parse; after `JSMN_ERROR_NOMEM` calling again with a larger array continues and yields the same result.
R10. String escapes `\" \/ \\ \b \f \r \n \t \uXXXX` validated; bad escape, bad/short \u hex => INVAL (truncated => PART); unterminated string => PART.
R11. Unterminated object/array at end of input => PART. Unmatched closing bracket (also mismatched type) => INVAL.
R12. Control characters/invalid starts: non-strict is lenient as original jsmn; in strict, unexpected chars => INVAL.
R13. STRICT: primitives must be valid JSON literal/number (grammar: -?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?, true/false/null); primitives cannot be object keys; primitive must be followed by delimiter, else INVAL; `:` and `,` structure enforced (colon after key, no leading/trailing garbage in tokens).
R14. PARENT_LINKS: `parent` = index of enclosing token or -1 for root; closing bracket matching walks via parent links (O(1) per level).
R15. NOMEM when tokens array exhausted; num_tokens==0 with non-NULL tokens => NOMEM on first token.
R16. Empty input / whitespace only returns 0 tokens.
R17. Multiple top-level values are tokenised (as original jsmn); documented.
R18. Makefile: `make test` builds and runs the test-suite under default, STRICT, PARENT_LINKS, both; `make examples`, `make clean`; examples tested in `make test`.
R19. `simple.c`: extracts fields from a JSON object and prints them. `jsondump.c`: reads stdin, pretty-prints indented, growing token array via realloc on NOMEM, handles errors with exit code 1.
R20. README: what/why, API, config macros, build/test, design, limitations.

## Assumptions
- Follows original jsmn 1.x semantics where spec is silent (colon handling: a ':' sets toksuper to key token; a ',' pops toksuper back to container, in non-strict mode too).
- Non-strict mode accepts keys that are primitives and unquoted values.
- Token `size` of a string key increments when its value is added.
- Test failures counted by custom minimal harness (no external deps).

## Test strategy
tests/test.c: table-driven cases for R4-R17 (each config-aware via #ifdefs), resumability loops (byte-by-byte feeding, token-by-token growth), counting vs real parse equivalence, a randomized/fuzz robustness test (no crash, never exceed bounds, deterministic LCG). Examples: shell smoke in Makefile (`simple` output compare, `jsondump` on sample).
