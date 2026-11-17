import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import slugify, {slugifyWithCounter} from '../index.js';

const eq = (input, expected, options) => assert.equal(slugify(input, options), expected);

test('R1 spec examples', () => {
	eq('I ♥ Dogs', 'i-love-dogs');
	eq('  Déjà Vu!  ', 'deja-vu');
	eq('fooBar 123 $#%', 'foo-bar-123');
	eq('Conway’s Law', 'conways-law');
	eq('я люблю единорогов', 'ya-lyublyu-edinorogov');
});

test('R2 words, collapsing and trimming', () => {
	eq('', '');
	eq('!!!', '');
	eq('--a---b--', 'a-b');
	eq('a_b.c/d', 'a-b-c-d');
	eq('  a  ', 'a');
	eq('日本語', '');
});

test('R3 apostrophes removed inside words', () => {
	eq("it's", 'its');
	eq('rock \'n\' roll', 'rock-n-roll');
	eq('dʼArtagnan', 'dartagnan');
});

test('R4 separator', () => {
	eq('foo bar', 'foo_bar', {separator: '_'});
	eq('foo bar', 'foobar', {separator: ''});
	eq('foo bar baz', 'foo--bar--baz', {separator: '--'});
	eq('foo bar', 'foo.bar', {separator: '.'});
	eq('foo bar', 'foo$bar', {separator: '$'});
	assert.throws(() => slugify('a', {separator: 1}), TypeError);
});

test('R5 lowercase', () => {
	eq('Foo Bar', 'Foo-Bar', {lowercase: false});
	eq('Foo Bar', 'foo-bar', {lowercase: true});
});

test('R6 decamelize', () => {
	eq('fooBar', 'foo-bar');
	eq('APISection', 'api-section');
	eq('fooBAR', 'foo-bar');
	eq('FOO360', 'foo-360');
	eq('foo360BAR', 'foo360-bar');
	eq('foo360', 'foo360');
	eq('fooBar', 'foobar', {decamelize: false});
	eq('fooBar', 'foo-Bar', {lowercase: false});
	eq('ÜberFluss', 'uber-fluss');
});

test('R7 customReplacements', () => {
	eq('a & b', 'a-and-b');
	eq('🦄', 'unicorn');
	eq('a & b', 'a-plus-b', {customReplacements: [['&', ' plus ']]});
	eq('a & b ♥', 'a-plus-b-love', {customReplacements: new Map([['&', ' plus ']])});
	eq('x@y', 'x-at-y', {customReplacements: [['@', ' at ']]});
	eq('fooBar', 'foobar', {customReplacements: [['fooBar', 'foobar']]});
	assert.throws(() => slugify('a', {customReplacements: 5}), TypeError);
	assert.throws(() => slugify('a', {customReplacements: [['a']]}), TypeError);
});

test('R8 preserveLeadingUnderscore', () => {
	eq('_foo bar', 'foo-bar');
	eq('_foo bar', '_foo-bar', {preserveLeadingUnderscore: true});
	eq('__foo', '_foo', {preserveLeadingUnderscore: true});
	eq('foo', 'foo', {preserveLeadingUnderscore: true});
});

test('R9 preserveTrailingDash', () => {
	eq('foo-', 'foo');
	eq('foo-', 'foo-', {preserveTrailingDash: true});
	eq('foo', 'foo', {preserveTrailingDash: true});
});

test('R10 preserveCharacters', () => {
	eq('foo #bar', 'foo-#bar', {preserveCharacters: ['#']});
	eq('a#b', 'a#b', {preserveCharacters: ['#']});
	eq('a.b-c-', 'a.b-c-', {preserveCharacters: ['.'], preserveTrailingDash: true});
	eq('a]b^c\\d', 'a]b^c\\d', {preserveCharacters: [']', '^', '\\']});
	eq('ä b', 'ä-b', {preserveCharacters: ['ä']});
	assert.throws(() => slugify('a', {preserveCharacters: ['-']}), /separator/);
	assert.throws(() => slugify('a', {separator: '_', preserveCharacters: ['_']}));
	assert.throws(() => slugify('a', {preserveCharacters: '#'}), TypeError);
});

test('R11 locale', () => {
	eq('Über Äpfel Öl', 'uber-apfel-ol');
	eq('Über Äpfel Öl', 'ueber-aepfel-oel', {locale: 'de'});
	eq('Über', 'ueber', {locale: 'de-AT'});
	eq('Åsa Ärlig Örn', 'aasa-aerlig-oern', {locale: 'sv'});
	eq('Blåbær Øl', 'blaabaer-oel', {locale: 'da'});
	eq('Blåbær Øl', 'blaabaer-oel', {locale: 'nb'});
	eq('Åsa æ ø', 'asa-ae-o');
	eq('Гарно', 'harno', {locale: 'uk'});
	eq('Гарно', 'garno');
	eq('Straße', 'strasse');
	eq('x', 'x', {locale: 'zz'});
	assert.throws(() => slugify('x', {locale: 5}), TypeError);
});

test('R12 transliterate:false', () => {
	eq('Привет Мир', 'привет-мир', {transliterate: false});
	eq('Ünï Café!', 'ünï-café', {transliterate: false});
	eq('Ünï Café', 'Ünï-Café', {transliterate: false, lowercase: false});
	eq('日本 語', '日本-語', {transliterate: false});
	eq('a ♥ b', 'a-love-b', {transliterate: false});
});

test('R15 scripts', () => {
	eq('Việt Nam Đà Nẵng', 'viet-nam-da-nang');
	eq('Şişli İstanbul ığ', 'sisli-istanbul-ig');
	eq('Łódź Žluťoučký Æsir', 'lodz-zlutoucky-aesir');
	eq('Ελληνικά Θεσσαλονίκη', 'ellinika-thessaloniki');
	eq('Київ Їжак Ґанок', 'kiyiv-yizhak-ganok');
	eq('Београд Ђорђе Љубав', 'beograd-djordje-ljubav');
	eq('Қазақстан Әлем', 'qazaqstan-alem');
	eq('Щука Ёлка', 'shchuka-yolka');
	eq('مرحبا', 'mrhba');
	eq('چای گرم', 'chay-grm');
	eq('Հայաստան', 'hayastan');
	eq('საქართველო', 'sakartvelo');
	eq('שלום', 'shlvm');
	eq('price 5€ ½', 'price-5-euro-1-2');
	eq('٢٠٢٤', '2024');
	eq('ﬁne ２', 'fine-2');
	eq('x™ y®', 'x-y');
});

test('R14 TypeErrors', () => {
	for (const value of [undefined, null, 1, {}, [], true, Symbol('s')]) {
		assert.throws(() => slugify(value), TypeError);
	}

	assert.throws(() => slugify('a', null), TypeError);
	assert.throws(() => slugify('a', 'x'), TypeError);
	assert.throws(() => slugify('a', []), TypeError);
});

test('R17 purity and determinism', () => {
	const opts = Object.freeze({customReplacements: Object.freeze([['&', ' n ']])});
	assert.equal(slugify('a&b', opts), 'a-n-b');
	assert.equal(slugify('a&b', opts), 'a-n-b');
	eq('&', 'and');
	eq('♥♥', 'love-love');
});

test('R13 slugifyWithCounter', () => {
	const counter = slugifyWithCounter();
	assert.equal(counter('foo bar'), 'foo-bar');
	assert.equal(counter('foo bar'), 'foo-bar-2');
	assert.equal(counter('Foo Bar'), 'foo-bar-3');
	assert.equal(counter('other'), 'other');
	assert.equal(counter('foo-2'), 'foo-2');
	assert.equal(counter('foo-2'), 'foo-2-2');
	counter('x');
	counter('x');
	assert.equal(counter('x-2'), 'x-2-2');
	assert.equal(counter('x'), 'x-3');
	counter.reset();
	assert.equal(counter('foo bar'), 'foo-bar');
	assert.equal(counter('foo bar'), 'foo-bar-2');
	assert.equal(typeof counter.reset, 'function');
	assert.throws(() => counter(1), TypeError);
});

test('R13 counter options and independence', () => {
	const a = slugifyWithCounter();
	const b = slugifyWithCounter();
	a('x');
	assert.equal(b('x'), 'x');
	assert.equal(a('x', {separator: '_'}), 'x_2');
	assert.equal(a('y z', {separator: '_'}), 'y_z');
	assert.equal(a('y z', {separator: '_'}), 'y_z_2');
	assert.equal(a('X', {lowercase: false}), 'X');
});

test('R16 package manifest and declarations', () => {
	const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url)));
	assert.equal(pkg.type, 'module');
	assert.equal(pkg.types, './index.d.ts');
	assert.match(pkg.engines.node, /18/);
	assert.equal(pkg.dependencies, undefined);
	const dts = readFileSync(new URL('../index.d.ts', import.meta.url), 'utf8');
	for (const name of ['export default function slugify', 'slugifyWithCounter', 'preserveCharacters', 'transliterate', 'reset()']) {
		assert.ok(dts.includes(name), name);
	}
});

test('R2/R15 edge inputs: emoji, combining marks, prototype-like words, locale case', () => {
	eq('😀 hi 👍', 'hi');
	eq('مَرْحَبًا', 'mrhba');
	eq('áb', 'ab');
	eq('__proto__ constructor', 'proto-constructor');
	eq('Ünï', 'ueni', {locale: 'DE'});
	eq('foo-', 'foo-', {preserveTrailingDash: true, separator: '_'});
	eq('X-Y', 'x-y', {preserveCharacters: ['-'], separator: '_'});
});
