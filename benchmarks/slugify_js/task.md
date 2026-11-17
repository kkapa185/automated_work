# WEB-305: `slugify` — turn arbitrary strings into URL/filename-safe slugs (Node.js ESM library)

Build a dependency-light ES-module npm package (Node >= 18) whose default export is
`slugify(string, options?)` and which also exports `slugifyWithCounter()`. Implement the transliteration
yourself (tables for Latin with diacritics incl. German/Scandinavian/Vietnamese/Turkish, Greek,
Cyrillic incl. Russian/Ukrainian/Serbian/Kazakh-style letters, Arabic, Persian, Armenian, Georgian, Hebrew
approximations, common symbols) — do **not** depend on any `@sindresorhus/*` package or other slug /
transliteration library.

Behaviour:
* `slugify('I ♥ Dogs')` → `'i-love-dogs'`; `'  Déjà Vu!  '` → `'deja-vu'`; `'fooBar 123 $#%'` →
  `'foo-bar-123'`; `'Conway’s Law'` → `'conways-law'` (apostrophes inside words are removed, not
  separated); `'я люблю единорогов'` → `'ya-lyublyu-edinorogov'`.
* Words are runs of ASCII letters/digits after transliteration; everything else becomes the separator;
  repeated separators collapse; no leading/trailing separators.
* Options:
  - `separator` (default `'-'`; may be `''` or multi-character).
  - `lowercase` (default `true`).
  - `decamelize` (default `true`): `fooBar` → `foo bar`, acronyms handled (`APISection` → `api-section`,
    `fooBAR` → `foo-bar`, `FOO360` → `foo-360`, `foo360BAR` → `foo360-bar`).
  - `customReplacements` (default `[['&', ' and '], ['🦄', ' unicorn '], ['♥', ' love ']]`): array of
    `[from, to]` pairs applied to the original string before decamelization and transliteration; user
    entries override defaults with the same key and are otherwise added.
  - `preserveLeadingUnderscore` (default `false`): keep a single leading `_`.
  - `preserveTrailingDash` (default `false`): keep a trailing `-` if the input ends with one.
  - `preserveCharacters` (default `[]`): characters that are kept as-is (e.g. `['#']`); they may not
    include the separator.
  - `locale`: language-specific transliteration (e.g. `'de'`: `ä`→`ae`, `ö`→`oe`, `ü`→`ue`; default maps
    `ä`→`a`, etc. except where the general table says otherwise; `'sv'`, `'da'`/`'nb'` style rules).
  - `transliterate` (default `true`): when `false`, non-ASCII letters/digits are kept (still lowercased,
    separators applied).
* `slugifyWithCounter()` returns a function that slugifies and appends `-2`, `-3`, ... to repeated
  slugs (taking into account slugs that already end in a number), with a `.reset()` method.
* Throws `TypeError` for non-string input.

Ship TypeScript declarations (`index.d.ts`), a README with the API, and a comprehensive `node --test` suite.
