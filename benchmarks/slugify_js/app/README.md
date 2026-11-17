# slugify-lite

Dependency-free ES-module library (Node >= 18) that turns arbitrary strings into URL/filename-safe slugs.
Transliteration tables are built in: Latin with diacritics (German, Scandinavian, Vietnamese, Turkish, Polish, Czech…),
Greek, Cyrillic (Russian, Ukrainian, Serbian, Kazakh-style letters), Arabic, Persian, Armenian, Georgian, Hebrew
(approximation) and common symbols.

## Install / run / test

```sh
npm install        # no dependencies; nothing is downloaded
npm test           # node --test test/
npm run smoke      # quick end-to-end check
```

## Usage

```js
import slugify, {slugifyWithCounter} from './index.js';

slugify('I ♥ Dogs');             // 'i-love-dogs'
slugify('  Déjà Vu!  ');         // 'deja-vu'
slugify('fooBar 123 $#%');       // 'foo-bar-123'
slugify('Conway’s Law');         // 'conways-law'
slugify('я люблю единорогов');   // 'ya-lyublyu-edinorogov'
slugify('Über', {locale: 'de'}); // 'ueber'

const counter = slugifyWithCounter();
counter('foo bar'); // 'foo-bar'
counter('foo bar'); // 'foo-bar-2'
counter.reset();
```

## API

`slugify(string, options?)` — throws `TypeError` for a non-string input or malformed options.

| Option | Default | Description |
| --- | --- | --- |
| `separator` | `'-'` | Joins words; may be `''` or multi-character. |
| `lowercase` | `true` | Lowercase the result. |
| `decamelize` | `true` | `fooBar`→`foo-bar`, `APISection`→`api-section`, `FOO360`→`foo-360`, `foo360BAR`→`foo360-bar`. |
| `customReplacements` | `[['&',' and '],['🦄',' unicorn '],['♥',' love ']]` | `[from, to]` pairs (array or `Map`) applied to the original string first; same key overrides a default, others are added. |
| `preserveLeadingUnderscore` | `false` | Keep a single leading `_`. |
| `preserveTrailingDash` | `false` | Keep a trailing `-` if the input ends with one. |
| `preserveCharacters` | `[]` | Characters kept as-is (e.g. `['#']`). Throws if it contains the separator. |
| `locale` | – | `de` (ä→ae, ö→oe, ü→ue), `sv`/`fi` (å→aa, ä→ae, ö→oe), `da`/`nb`/`nn`/`no` (å→aa, æ→ae, ø→oe), `uk`, `bg`. Region tags such as `de-AT` work. |
| `transliterate` | `true` | If `false`, non-ASCII letters/digits are kept (still lowercased and separated). |

`slugifyWithCounter()` returns `counter(string, options?)` which appends `-2`, `-3`, … to repeated slugs
(a first-seen slug that already ends in a number, such as `foo-2` after two `foo`, is itself treated as a repeat
and becomes `foo-2-2`), plus `counter.reset()`. TypeScript declarations are in `index.d.ts`.

## Design

Pipeline: custom replacements → NFC → decamelize → per-character conversion (preserved chars, apostrophe removal,
locale table, general table, then NFKD fallback with combining marks stripped; unknown characters become separators)
→ lowercase → extract words (`[a-zA-Z0-9]+`) and join with the separator, then re-attach the preserved underscore/dash.
Tables live in `lib/tables.js`; upper-case entries are derived from lower-case ones.
Unmapped scripts (e.g. CJK) are treated as separators unless `transliterate: false`.
