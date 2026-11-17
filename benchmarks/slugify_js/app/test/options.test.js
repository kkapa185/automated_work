import test from 'node:test';
import assert from 'node:assert/strict';
import slugify from '../index.js';

test('R2 non-string input throws TypeError', () => {
	for (const value of [1, null, undefined, {}, [], true, Symbol('x'), ['a']]) {
		assert.throws(() => slugify(value), TypeError);
	}
});

test('R2 invalid options throw TypeError', () => {
	assert.throws(() => slugify('a', null), TypeError);
	assert.throws(() => slugify('a', 'x'), TypeError);
	assert.throws(() => slugify('a', {preserveCharacters: '#'}), TypeError);
	assert.throws(() => slugify('a', {customReplacements: [[1, 'a']]}), TypeError);
});

test('R4 NFC normalisation and custom replacement matching', () => {
	assert.equal(slugify('été'), 'ete');
	assert.equal(slugify('é', {customReplacements: [['é', 'X']]}), 'x');
});

test('R5 word runs, collapsing and trimming', () => {
	assert.equal(slugify(''), '');
	assert.equal(slugify('   '), '');
	assert.equal(slugify('$#%!'), '');
	assert.equal(slugify('--a---b__c  d--'), 'a-b-c-d');
	assert.equal(slugify('a.b/c\\d'), 'a-b-c-d');
	assert.equal(slugify('日本語 abc'), 'abc');
});

test('R6 apostrophes', () => {
	assert.equal(slugify('don\'t stop'), 'dont-stop');
	assert.equal(slugify('rock \'n\' roll'), 'rock-n-roll');
	assert.equal(slugify('it’s'), 'its');
	assert.equal(slugify('Conway\'s Law', {preserveCharacters: ['\'']}), 'conways-law');
	assert.equal(slugify('don\'t', {preserveCharacters: ['\'']}), 'dont');
	assert.equal(slugify('o\'brien', {preserveCharacters: ['\'']}), 'o\'brien');
});

test('R7 multi-character separator', () => {
	assert.equal(slugify('a b c', {separator: '--'}), 'a--b--c');
	assert.equal(slugify('  a b  ', {separator: '__'}), 'a__b');
	assert.equal(slugify('foo bar', {separator: '.'}), 'foo.bar');
});

test('R9 decamelize rules', () => {
	assert.equal(slugify('APISection'), 'api-section');
	assert.equal(slugify('fooBAR'), 'foo-bar');
	assert.equal(slugify('FOO360'), 'foo-360');
	assert.equal(slugify('foo360BAR'), 'foo360-bar');
	assert.equal(slugify('foo360'), 'foo360');
	assert.equal(slugify('Foo360'), 'foo360');
	assert.equal(slugify('fooBarBaz'), 'foo-bar-baz');
	assert.equal(slugify('FooBar', {lowercase: false}), 'Foo-Bar');
	assert.equal(slugify('APISection', {decamelize: false}), 'apisection');
});

test('R10 default replacements and overriding', () => {
	assert.equal(slugify('BAR & baz'), 'bar-and-baz');
	assert.equal(slugify('🦄'), 'unicorn');
	assert.equal(slugify('a♥b'), 'a-love-b');
	assert.equal(slugify('a & b', {customReplacements: [['&', ' et ']]}), 'a-et-b');
	assert.equal(slugify('a & 🦄', {customReplacements: [['&', ' et ']]}), 'a-et-unicorn');
	assert.equal(slugify('a & b', {customReplacements: new Map([['&', '']])}), 'a-b');
	assert.equal(slugify('a.b', {customReplacements: [['.', ' dot ']]}), 'a-dot-b');
});

test('R10 replacements are applied before decamelize and not re-applied', () => {
	assert.equal(slugify('x', {customReplacements: [['x', 'fooBar']]}), 'foo-bar');
	assert.equal(slugify('ab', {customReplacements: [['a', 'b'], ['b', 'c']]}), 'bc');
});

test('R11 leading underscore', () => {
	assert.equal(slugify('__foo', {preserveLeadingUnderscore: true}), '_foo');
	assert.equal(slugify('foo_', {preserveLeadingUnderscore: true}), 'foo');
});

test('R12 trailing dash', () => {
	assert.equal(slugify('foo-bar---', {preserveTrailingDash: true}), 'foo-bar-');
	assert.equal(slugify('foo bar', {preserveTrailingDash: true}), 'foo-bar');
	assert.equal(slugify('foo-bar- ', {preserveTrailingDash: true}), 'foo-bar');
});

test('R13 preserveCharacters', () => {
	assert.equal(slugify('a#b c', {preserveCharacters: ['#']}), 'a#b-c');
	assert.equal(slugify('a.b-c', {preserveCharacters: ['.']}), 'a.b-c');
	assert.equal(slugify('a]b^c', {preserveCharacters: [']', '^']}), 'a]b^c');
	assert.equal(slugify('café', {preserveCharacters: ['é']}), 'café');
	assert.throws(() => slugify('a', {preserveCharacters: ['-']}), /separator/);
	assert.throws(() => slugify('a', {separator: '_', preserveCharacters: ['_']}), /separator/);
	assert.equal(slugify('a_b', {separator: '', preserveCharacters: ['_']}), 'a_b');
});

test('R14 locales', () => {
	assert.equal(slugify('Ö'), 'oe');
	assert.equal(slugify('Ö', {lowercase: false}), 'Oe');
	assert.equal(slugify('Ö', {locale: 'sv'}), 'o');
	assert.equal(slugify('Räksmörgås', {locale: 'sv-SE'}), 'raksmorgas');
	assert.equal(slugify('Räksmörgås', {locale: 'de'}), 'raeksmoergas');
	assert.equal(slugify('Blåbærgrød', {locale: 'da'}), 'blaabaergroed');
	assert.equal(slugify('Blåbærgrød', {locale: 'nb'}), 'blabaergrod');
	assert.equal(slugify('ığş', {locale: 'tr'}), 'igs');
	assert.equal(slugify('Київ Гора', {locale: 'uk'}), 'kyiv-hora');
	assert.equal(slugify('Гора'), 'gora');
	assert.equal(slugify('Räksmörgås', {locale: 'xx'}), 'raeksmoergas');
	assert.equal(slugify('Räksmörgås', {locale: ''}), 'raeksmoergas');
});

test('R15 transliterate false', () => {
	assert.equal(slugify('Déjà Vu!', {transliterate: false, lowercase: false}), 'Déjà-Vu');
	assert.equal(slugify('Я люблю 日本', {transliterate: false}), 'я-люблю-日本');
	assert.equal(slugify('I ♥ Dogs', {transliterate: false}), 'i-love-dogs');
	assert.equal(slugify('x\u0301a', {transliterate: false}), 'x\u0301a');
});

test('R20 idempotence on default options', () => {
	for (const input of ['I ♥ Dogs', 'Déjà Vu!', 'fooBar 123 $#%', 'я люблю единорогов', 'Conway’s Law', 'APISection FOO360', '  ---  ', 'Ελληνικά']) {
		const once = slugify(input);
		assert.equal(slugify(once), once);
	}
});
