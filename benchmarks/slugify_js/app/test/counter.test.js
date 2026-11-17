import test from 'node:test';
import assert from 'node:assert/strict';
import {slugifyWithCounter} from '../index.js';

test('R16 counter increments', () => {
	const s = slugifyWithCounter();
	assert.equal(s('Foo Bar'), 'foo-bar');
	assert.equal(s('foo bar'), 'foo-bar-2');
	assert.equal(s('FOO BAR'), 'foo-bar-3');
	assert.equal(s('other'), 'other');
});

test('R16 slugs already ending in a number never collide', () => {
	const s = slugifyWithCounter();
	assert.equal(s('foo 2'), 'foo-2');
	assert.equal(s('foo'), 'foo');
	assert.equal(s('foo'), 'foo-3');
	assert.equal(s('foo 2'), 'foo-2-2');
	const seen = new Set();
	for (const input of ['a', 'a 2', 'a', 'a', 'a 2', 'a 3', 'a']) {
		const out = s(input);
		assert.ok(!seen.has(out), out);
		seen.add(out);
	}
});

test('R16 reset and independent instances; options passed through', () => {
	const a = slugifyWithCounter();
	const b = slugifyWithCounter();
	a('x');
	assert.equal(a('x'), 'x-2');
	assert.equal(b('x'), 'x');
	a.reset();
	assert.equal(a('x'), 'x');
	assert.equal(a('x', {separator: '_'}), 'x_2');
	assert.equal(a('x', {separator: '_'}), 'x_3');
});

test('R2 counter throws TypeError for non-strings', () => {
	assert.throws(() => slugifyWithCounter()(5), TypeError);
});
