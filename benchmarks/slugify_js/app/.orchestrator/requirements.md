# WEB-305 slugify — requirements

## Product
A dependency-free Node >= 18 ES-module npm package. Default export `slugify(string, options?)` turns arbitrary
Unicode text into an ASCII URL/filename-safe slug using a self-written transliteration table (Latin+diacritics incl.
German/Nordic/Vietnamese/Turkish, Greek, Cyrillic, Arabic, Persian, Armenian, Georgian, Hebrew, symbols). Named export
`slugifyWithCounter()` yields unique slugs. Ships `index.d.ts`, README and a `node --test` suite. `docs/README.md` is normative.

## Acceptance criteria
R1  Default export `slugify`; named exports `slugifyWithCounter` (and default also available as named `slugify`). No runtime deps; no sindresorhus/slug/translit packages.
R2  Non-string input (number, null, undefined, object, array) throws `TypeError`.
R3  Examples: 'I ♥ Dogs'→'i-love-dogs'; '  Déjà Vu!  '→'deja-vu'; 'fooBar 123 $#%'→'foo-bar-123'; 'Conway’s Law'→'conways-law'; 'я люблю единорогов'→'ya-lyublyu-edinorogov'.
R4  Input is NFC-normalised first; customReplacements keys are matched against the normalised text (NFC-normalise keys too).
R5  Words = runs of [A-Za-z0-9] after transliteration; everything else is a separator; repeated separators collapse; no leading/trailing separators (except R14/R15). Empty/all-symbol input → ''.
R6  Apostrophes (' and ’) between word characters are removed, not separated ("don't"→"dont"). With `preserveCharacters` containing an apostrophe, a word-final `'s`/`'t` apostrophe is still dropped; other apostrophes are kept.
R7  `separator` default '-'; '' and multi-char allowed: 'BAR and baz' → 'bar-and-baz' / 'bar_and_baz' / 'barandbaz'.
R8  `lowercase` default true; false: 'Déjà Vu!'→'Deja-Vu'.
R9  `decamelize` default true: fooBar→'foo-bar'; false→'foobar'; APISection→'api-section'; fooBAR→'foo-bar'; FOO360→'foo-360'; foo360BAR→'foo360-bar'.
R10 `customReplacements` default [['&',' and '],['🦄',' unicorn '],['♥',' love ']]; user pairs override same key, otherwise are added (accepts arrays of pairs and Map/iterables of pairs). Applied to the original (normalised) string before decamelize/transliterate. Examples: 'Foo@unicorn' with [['@','at']]→'fooatunicorn'; 'foo@unicorn' with [['@',' at ']]→'foo-at-unicorn'; 'I love 🐶' with [['🐶','dogs']]→'i-love-dogs'. Default '&': 'BAR & baz'→'bar-and-baz'; '🦄'→'unicorn'.
R11 `preserveLeadingUnderscore` (default false): '_foo_bar'→'foo-bar'; true→'_foo-bar'. Only a single leading underscore kept ('__foo'→'_foo').
R12 `preserveTrailingDash` (default false): 'foo-bar-'→'foo-bar'; true→'foo-bar-'. If the slug would be empty, no dash added beyond what the input implies (see assumptions).
R13 `preserveCharacters` (default []): listed chars kept as-is: 'foo_bar#baz' with ['#']→'foo-bar#baz'. If it contains the separator → throws (assumed Error/TypeError? see assumptions). Chars are regex-escaped.
R14 `locale`: general table maps ä→ae, ö→oe, ü→ue, ß→ss (German digraphs; Ö→Oe→'oe'): 'Räksmörgås'→'raeksmoergas'; {locale:'sv'}→'raksmorgas'. Locales: de, da, nb/no/nn, sv, fi, et, tr, uk, ru, bg, sr, mk, cs, sk, pl-ish etc. as reasonable; locale tags like 'sv-SE' resolve to 'sv'; unknown locale = general table.
R15 `transliterate` default true; false keeps non-ASCII letters/digits (Unicode \p{L}\p{N}, lowercased): 'Déjà Vu' → 'déjà-vu'. Custom replacements and decamelize still apply.
R16 `slugifyWithCounter()` returns fn(string, options?) giving slug, then `slug-2`, `slug-3`, … for repeats; handles slugs already ending in a number (e.g. 'foo-2' then 'foo' then 'foo' must never return a duplicate: 'foo-2','foo','foo-3'? — all outputs unique); `.reset()` clears. Spec examples: 'foo bar','foo bar'→'foo-bar','foo-bar-2'; after reset 'foo-bar'. Independent instances have independent state.
R17 Transliteration coverage tests for each script: Latin (é ñ ç ø å æ œ ß Đ đ ł Ş ğ İ ı, Vietnamese ế ạ ơ ư), Greek, Cyrillic (ru, uk є і ї ґ, sr ђ ј љ њ ћ џ, kk ә ғ қ ң ө ұ ү һ), Arabic, Persian (پ چ ژ گ), Armenian, Georgian, Hebrew, symbols (© ® ™ € £ ¥ ° ½ etc.). Output always ASCII when transliterate true.
R18 `index.d.ts` declares Options, default export, slugifyWithCounter (with reset); package.json: type module, engines node>=18, exports/types, scripts.test = `node --test`.
R19 README: install, usage, API, design, tests. Every docs/README.md example is an automated test.
R20 Idempotence: slugify(slugify(x)) === slugify(x) for default options on assorted inputs.

## Assumptions
- Option validation for non-object options: treat undefined only; other → TypeError. preserveCharacters containing separator → throws `Error` (message names it).
- Decamelize rules (Unicode-aware, on text before transliteration): split lower/digit→Upper; Upper-run→Upper+lower (APISection); an Upper run of ≥2 followed by a digit splits (FOO360); 'Foo360' and 'foo360' do not split.
- Underscore is a normal separator unless preserved. preserveTrailingDash applies if the original input ends with '-' and slug non-empty.
- Counter: if candidate slug already used, bump a numeric suffix until unseen (tracks every emitted slug).
- Hebrew/Arabic transliterations are approximations (consonant skeleton).

## Test strategy
`node --test test/*.test.js`: examples.test.js (R3, README examples exactly), options.test.js (R7–R15), counter.test.js (R16), translit.test.js (R17, per-script expected values computed by hand), errors.test.js (R2, R13), property-style tests (R5, R17 ASCII-only, R20) over a fixed corpus; types check via file-content test of index.d.ts.
