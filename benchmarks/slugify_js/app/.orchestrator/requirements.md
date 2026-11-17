# Requirements: slugify (Node.js ESM library)

## Product
A dependency-free ES-module npm package (Node >= 18). Default export `slugify(string, options?)` converts arbitrary Unicode strings to URL/filename-safe slugs using built-in transliteration tables (Latin+diacritics, Greek, Cyrillic, Arabic, Persian, Armenian, Georgian, Hebrew, symbols). Also exports `slugifyWithCounter()`. Ships `index.d.ts`, README and a `node --test` suite. Classification: library.

## Acceptance criteria
R1. `slugify('I ♥ Dogs')`=`i-love-dogs`; `'  Déjà Vu!  '`=`deja-vu`; `'fooBar 123 $#%'`=`foo-bar-123`; `'Conway’s Law'`=`conways-law`; `'я люблю единорогов'`=`ya-lyublyu-edinorogov`.
R2. Words are runs of [a-zA-Z0-9] after transliteration; all else is separator; repeats collapse; no leading/trailing separators.
R3. Apostrophes (' ’ ʼ ‘) inside words are removed (not separated).
R4. `separator` option (default `-`; `''` and multi-char allowed; regex-special chars safe).
R5. `lowercase` (default true); false preserves case.
R6. `decamelize` (default true): `fooBar`→`foo-bar`, `APISection`→`api-section`, `fooBAR`→`foo-bar`, `FOO360`→`foo-360`, `foo360BAR`→`foo360-bar`; false disables.
R7. `customReplacements` array of `[from,to]` (also accepts Map/iterables); applied on original string before decamelize/transliteration; user entries override defaults of the same key, others added. Defaults `&`→` and `, `🦄`→` unicorn `, `♥`→` love `.
R8. `preserveLeadingUnderscore` keeps one leading `_` (even if multiple underscores).
R9. `preserveTrailingDash` keeps a trailing `-` if input ends with `-`.
R10. `preserveCharacters` array of chars kept as-is; throws if it includes the separator (non-empty).
R11. `locale`: `de` (ä→ae, ö→oe, ü→ue, Ä/Ö/Ü too), `sv` (å→aa, ä→ae, ö→oe), `da`/`nb`/`no` (å→aa, æ→ae, ø→oe), plus `vi`, `tr`-ish fallbacks to general table; accepts `de-AT` style tags (language subtag). Default: ä→a, ö→o, ü→u, ß→ss, æ→ae, ø→o, å→a.
R12. `transliterate:false`: keep Unicode letters/digits (lowercased), other chars → separator; custom replacements still apply.
R13. `slugifyWithCounter()` returns fn; repeats get `-2`,`-3`…; slugs already ending in number handled (`foo-2` seen, then `foo` → `foo-3`? see assumption A3); `.reset()` clears. Honors options and separator.
R14. Throws `TypeError` for non-string input (string, options, and options type for invalid options object).
R15. Transliteration tables covering Latin (German/Scandinavian/Vietnamese/Turkish/Polish/Czech etc.), Greek, Cyrillic (Russian/Ukrainian/Serbian/Kazakh), Arabic, Persian, Armenian, Georgian, Hebrew, symbols (©, ®, ™, €, £, °, %→ separator, etc.). Unknown non-ASCII chars act as separators.
R16. Package: package.json (type module, exports, types, engines >=18, `npm test`), index.d.ts, README, no dependencies.
R17. Input immutability, empty string → `''`, string of only symbols → `''`.

## Assumptions
A1. Combining marks are stripped after NFD fallback. A2. Counter: keeps a map of count per base slug; if input slug matches `^(.*)-(\d+)$` and base exists, the stored count is compared like sindre-style: the counter tracks the lowercase-stripped base `foo` and number; `foo-2` after `foo` x2 yields `foo-2-2`. Plain approach: track occurrences of each full slug; on repeat of slug S (count n>=2) emit `S-n`; for slug ending in number `S-N` (S,N) the first occurrence is returned as is, repeat is `S-N-2`. A3. Also if generated `S-n` collides with an already-issued slug, increment further. A4. `%` and `$#` are separators. A5. `decamelize` runs on already-replaced string, before transliteration; lowercase false retains case. A6. `preserveCharacters` entries are escaped; only single code points considered per entry string chars.

## Test strategy
`node --test` unit tests in `test/`: spec examples (R1), each option (R4–R12), tables per script (R15), counter (R13), errors (R14), edge cases (R17), plus a d.ts presence/shape check and a package manifest check (R16).
