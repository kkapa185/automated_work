# Benchmark report — sindresorhus/slugify

**Ticket:** [`task.md`](task.md) (WEB-305). It asks for an ESM slug library with its own transliteration
tables: no `@sindresorhus/*` or other slug/transliteration dependency. From attempt 2 the workspace
also contains the project's public README (API docs).

**Reference execution:** the hidden harness [`compare.py`](compare.py):
1. runs the reference repo's **own test-suite** (`test.js`, 293 assertions in 89 tests) against the
   generated package;
2. differential-fuzzes 600 random strings and option sets through both implementations;
3. compares `slugifyWithCounter`.

## Score history
| attempt | system | score | reference tests passed | fuzz agreement |
|---|---|---|---|---|
| 1 | `86683d9` | 0.55 | 51/89 | 309/600 (51%) |
| 2 | `7c307c4` | 0.61 | 56/89 | 461/600 (77%) |

**Analysis:**
- Attempt 1 was hurt by a **ticket error**: I wrote that `ä` defaults to `a`; the reference's general table
  gives `ae`. Fixed in the ticket, and the README was provided as a normative input.
- The remaining gap is behaviour that appears only in the reference's hidden test-suite, not in its
  documentation. That covers:
  - Unicode normalisation details: NFC output, combining-mark limits, decomposed acronyms, titlecase boundaries;
  - `$`-patterns and ordering in custom replacements;
  - `preserveCharacters` overriding a default replacement (`foo&&bar` → `foo&&bar`);
  - counter suffixes on slugs that already end in a number;
  - Pashto/Armenian table entries.

  A README-level ticket cannot pin these down. Writing them into the ticket would amount to transcribing
  the hidden tests, so I stopped iterating.
- The generated library passes its own test-suite, has no forbidden dependencies, and handles all
  documented examples.

**Process (attempt 2):** 3 turns on one session. $1.36.
