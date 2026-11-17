# Benchmark report — zserge/jsmn

**Ticket:** [`task.md`](task.md) (EMB-90). It asks for a single-header, allocation-free JSON tokenizer in C89
with the `jsmn` API and its four build configurations.

**Reference execution:** the hidden harness [`compare.py`](compare.py) does three things:
- compiles the reference repo's **own test-suite** against the generated `jsmn.h` in all four
  configurations (default, strict, parent links, strict+links);
- builds a differential fuzzer against both headers and runs 705 malformed and valid snippets through it,
  comparing the return code, the token stream and counting mode (`tokens == NULL`);
- compiles the header as strict C89 with `-Wall -Wextra -Werror`.

## Score history
| attempt | score | gap |
|---|---|---|
| 1 | 0.64 | The reference test-suite passed in all 4 configurations, but two **ticket inaccuracies** caused mismatches. (a) In counting mode the reference skips token-dependent validation and returns partial counts for malformed input; the ticket was silent on this. (b) Strict mode in the reference is only *lexical*: `tru` and `01` are accepted. My ticket said primitives must be valid literals, so the generated header was *more* correct, but incompatible. |
| 2 | **1.00** | Both semantics are now written precisely in the ticket. Fuzz agreement is 705/705 in every configuration. |

The harness was also improved so that token-stream agreement and counting-mode agreement are scored
separately.

**Process (attempt 2):** 4 turns on one session.
