# slugify-lite

Turn arbitrary strings into URL/filename-safe slugs. Dependency-free ES module for Node >= 18 with its own
transliteration tables (Latin with diacritics incl. German/Scandinavian/Vietnamese/Turkish, Greek, Cyrillic incl.
Russian/Ukrainian/Serbian/Kazakh letters, Arabic, Persian, Armenian, Georgian, Hebrew approximations, common symbols).

## Install / test / run

```sh
npm install          # no dependencies; nothing to download
npm test             # node --test
node scripts/smoke.js
```

## Usage

```js
import slugify, {slugifyWithCounter} from 'slugify-lite';

slugify('I ♥ Dogs');              //=> 'i-love-dogs'
slugify('  Déjà Vu!  ');          //=> 'deja-vu'
slugify('fooBar 123 $#%');        //=> 'foo-bar-123'
slugify('Conway’s Law');          //=> 'conways-law'
slugify('я люблю единорогов');    //=> 'ya-lyublyu-edinorogov'
```

## API

### `slugify(string, options?)`
Throws `TypeError` if `string` is not a string.

| Option | Default | Meaning |
| --- | --- | --- |
| `separator` | `'-'` | Word separator; may be `''` or multi-character. |
| `lowercase` | `true` | Lowercase the slug. |
| `decamelize` | `true` | `fooBar` → `foo bar`; `APISection` → `api-section`, `fooBAR` → `foo-bar`, `FOO360` → `foo-360`, `foo360BAR` → `foo360-bar`. |
| `customReplacements` | `[['&',' and '],['🦄',' unicorn '],['♥',' love ']]` | `[from, to]` pairs (array or Map) applied to the NFC-normalised original before decamelization and transliteration. Same key overrides a default; others are added. |
| `preserveLeadingUnderscore` | `false` | Keep a single leading `_`. |
| `preserveTrailingDash` | `false` | Keep a trailing `-` if the input ends with one. |
| `preserveCharacters` | `[]` | Characters kept as-is (e.g. `['#']`). Must not include the separator (throws `Error`). The apostrophe in word-final `'s`/`'t` is still dropped. |
| `locale` | `undefined` | Language-specific transliteration (`'sv'`, `'de'`, `'da'`, `'nb'`, `'tr'`, `'uk'`, ...; `sv-SE` style tags accepted). `slugify('Räksmörgås')` → `'raeksmoergas'`, with `{locale: 'sv'}` → `'raksmorgas'`. |
| `transliterate` | `true` | When `false`, non-ASCII letters/digits are kept (`'Déjà Vu'` → `'déjà-vu'`). |

### `slugifyWithCounter()`
Returns a `slugify`-like function that appends `-2`, `-3`, ... to repeated slugs (never returning a slug it already
returned, even when slugs already end in a number) and has `.reset()`.

```js
const slugify = slugifyWithCounter();
slugify('foo bar'); //=> 'foo-bar'
slugify('foo bar'); //=> 'foo-bar-2'
slugify.reset();
slugify('foo bar'); //=> 'foo-bar'
```

TypeScript declarations are in `index.d.ts`.

## Design

Pipeline: NFC → custom replacements (single pass, longest key first) → decamelize → remove intra-word apostrophes →
transliterate (locale table, then general table, then generic diacritic stripping; unknown characters become
boundaries) → lowercase → split on anything that is not `[A-Za-z0-9]` (or a preserved character) → join with the
separator → optional leading underscore / trailing dash.
Code: `index.js`, `lib/tables.js` (general data), `lib/locales.js` (overrides), `lib/transliterate.js`.

## Assumptions
- Preserved leading underscore / trailing dash are only added when the slug is non-empty.
- Hebrew and Arabic output is a consonant skeleton approximation; Armenian `ու` becomes `ou`.
- The trailing dash kept is a literal `-`, regardless of separator.
