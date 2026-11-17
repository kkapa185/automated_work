import test from 'node:test';
import assert from 'node:assert/strict';
import slugify, {slugifyWithCounter, slugify as named} from '../index.js';

const cases = [
	// R3
	['I ♥ Dogs', undefined, 'i-love-dogs'],
	['  Déjà Vu!  ', undefined, 'deja-vu'],
	['fooBar 123 $#%', undefined, 'foo-bar-123'],
	['Conway’s Law', undefined, 'conways-law'],
	['я люблю единорогов', undefined, 'ya-lyublyu-edinorogov'],
	// R7
	['BAR and baz', undefined, 'bar-and-baz'],
	['BAR and baz', {separator: '_'}, 'bar_and_baz'],
	['BAR and baz', {separator: ''}, 'barandbaz'],
	// R8
	['Déjà Vu!', undefined, 'deja-vu'],
	['Déjà Vu!', {lowercase: false}, 'Deja-Vu'],
	// R9
	['fooBar', undefined, 'foo-bar'],
	['fooBar', {decamelize: false}, 'foobar'],
	// R10
	['Foo@unicorn', {customReplacements: [['@', 'at']]}, 'fooatunicorn'],
	['foo@unicorn', {customReplacements: [['@', ' at ']]}, 'foo-at-unicorn'],
	['I love 🐶', {customReplacements: [['🐶', 'dogs']]}, 'i-love-dogs'],
	// R11
	['_foo_bar', undefined, 'foo-bar'],
	['_foo_bar', {preserveLeadingUnderscore: true}, '_foo-bar'],
	// R12
	['foo-bar-', undefined, 'foo-bar'],
	['foo-bar-', {preserveTrailingDash: true}, 'foo-bar-'],
	// R13
	['foo_bar#baz', {preserveCharacters: ['#']}, 'foo-bar#baz'],
	// R14
	['Räksmörgås', undefined, 'raeksmoergas'],
	['Räksmörgås', {locale: 'sv'}, 'raksmorgas'],
	// R15
	['Déjà Vu', undefined, 'deja-vu'],
	['Déjà Vu', {transliterate: false}, 'déjà-vu']
];

for (const [input, options, expected] of cases) {
	test(`R3-R15 docs example: ${JSON.stringify(input)} ${JSON.stringify(options)}`, () => {
		assert.equal(slugify(input, options), expected);
	});
}

test('R1 exports', () => {
	assert.equal(named, slugify);
	assert.equal(typeof slugifyWithCounter, 'function');
});

test('R16 docs counter example', () => {
	const s = slugifyWithCounter();
	assert.equal(s('foo bar'), 'foo-bar');
	assert.equal(s('foo bar'), 'foo-bar-2');
	s.reset();
	assert.equal(s('foo bar'), 'foo-bar');
});
