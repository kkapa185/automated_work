# EMB-90 requirements

## Product
A C89, single-header, allocation-free, libc-free (only `<stddef.h>`) JSON tokenizer `jsmn.h`, API-compatible
with the de-facto `jsmn` library, plus Makefile (4-config test matrix), test suite, two examples
(`simple.c`, `jsondump.c`) and README. Kind of system: C library.

## Acceptance criteria
R1. `jsmn.h` is a single header; `JSMN_HEADER` yields declarations only; `JSMN_STATIC` makes functions `static`
    (`JSMN_API`). Only `<stddef.h>` is included. Compiles clean with `-std=c89 -pedantic -Wall -Wextra -Werror`.
R2. Exact public types: `jsmntype_t` (UNDEFINED=0, OBJECT=1, ARRAY=2, STRING=4, PRIMITIVE=8), `enum jsmnerr`
    (NOMEM -1, INVAL -2, PART -3), `jsmntok_t{type,start,end,size[,parent if JSMN_PARENT_LINKS]}`,
    `jsmn_parser{unsigned pos, unsigned toknext, int toksuper}`, `jsmn_init`, `jsmn_parse` with given signatures.
R3. `jsmn_init` sets pos=0,toknext=0,toksuper=-1.
R4. Tokens are `[start,end)` byte ranges; strings exclude quotes; object/array tokens span from opener to
    after closer; emitted in document order; `size` = direct children (object keys are children of the object;
    key has size 1 if it has a value).
R5. Primitives: numbers, true, false, null; non-strict: any other unquoted run of chars.
R6. Return value = tokens used; negative jsmnerr on failure. `tokens==NULL` => counting mode returns number of
    tokens needed.
R7. Counting mode skips checks needing token array: closer/opener matching, unclosed-at-end detection,
    key/value bookkeeping; so malformed inputs like `{"a":1` or `[}`-like mismatches may return the count.
    Character-level errors (bad escapes, illegal chars) still reported. Strict-mode checks on primitives'
    first char/terminator still apply (they are lexical).
R8. Resumable: same parser with longer buffer continues; PART = need more data (unterminated string, unclosed
    structures at end with tokens, strict primitive hitting end); NOMEM = need more tokens, parser state allows
    retry after growing the array (pos left at the failing token's start).
R9. String escapes `\" \/ \\ \b \f \r \n \t \uXXXX` (exactly 4 hex digits) validated, not decoded; invalid escape
    or bad \u => INVAL; string not closed before end => PART (parser pos restored to the opening quote).
    Control characters are not otherwise rejected.
R10. Unmatched closing bracket => INVAL; mismatched type (`{]`) => INVAL; unclosed at end => PART.
R11. STRICT: primitive must start with `-`, digit, `t`,`f`,`n` else INVAL; spelling unchecked (`tru`,`01`,`-` ok);
    terminators are whitespace, `,`, `]`, `}`; `:` is not a terminator (it simply becomes part of the primitive, e.g. `1:2`); primitive at end-of-input => PART;
    object/array/primitive cannot be object keys (INVAL); a comma/colon structure checks (`:` only after key
    string, `,` only in container with preceding value) per strict rules.
R12. Non-strict primitive terminators: `\t \r \n space , ] } :`; at end of input accepted as complete (non-strict);
    illegal chars (< 32 or >= 127) in primitive => INVAL.
R13. PARENT_LINKS: `parent` = index of enclosing token or -1; closing-bracket matching O(1) per level.
R14. Without PARENT_LINKS, closing matches by scanning backward for the innermost open (end == -1) token.
R15. Empty input / whitespace-only returns 0. Quoted strings as keys; key followed by value increments key size.
R16. Makefile: `make test` builds and runs the test suite in 4 configs (default, STRICT, PARENT_LINKS, both),
    also `make all` builds examples, `make clean`.
R17. Tests cover: every example in ticket; token boundaries/sizes/types; counting mode vs parse equality on valid
    input and the "skips checks" behaviour; errors; resumability (byte-by-byte feeding, NOMEM grow); strict specifics;
    parent links; escapes; JSMN_STATIC/HEADER include (multi-TU link test).
R18. `simple.c` extracts fields from a JSON object and prints them; `jsondump.c` reads stdin, pretty-prints,
    growing the token array (realloc) on NOMEM. Both are tested via Makefile target(s).
R19. README: purpose, API, build/test, config macros, semantics, design.

## Assumptions
A1. Token spans for strings: start/end are content only; containers: end set on closure.
A2. Non-strict: after a primitive/closing/string the parse follows the classic state machine; `:` sets toksuper
    to the previous token (the key); a value after a key pops super back to the container once value is complete
    (for strings/primitives in non-strict, kept lenient; in strict mode only a string may be a key).
A3. Strict key checks: when toksuper token is an OBJECT and a token other than STRING is started => INVAL;
    when toksuper is a key (STRING with size>0 after colon) a second consecutive value without comma => INVAL.
A4. Tests expected values derived by hand from the spec, not from implementation output.

## Test strategy
- `test/test.c` (own mini framework, no deps) compiled 4 ways; unit tests per R; a multi-TU test for JSMN_HEADER/
  JSMN_STATIC; examples run in `make test` with fixed input and output compared (simple: field extraction;
  jsondump: indentation output compare).

A5. Input processing stops at the first NUL byte or `len` (jsmn-compatible). Extra tests: sanitizer run clean (ASan/UBSan) in two configs.
