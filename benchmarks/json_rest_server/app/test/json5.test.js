'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { parse } = require('../src/json5');

test('R2 json5: README db.json5 example parses', () => {
  const v = parse(`{
  posts: [
    { id: "1", title: "a title", views: 100 },
    { id: "2", title: "another title", views: 200 },
  ],
  profile: {
    name: "typicode",
  },
}`);
  assert.deepEqual(v, { posts: [{ id: '1', title: 'a title', views: 100 }, { id: '2', title: 'another title', views: 200 }], profile: { name: 'typicode' } });
});

test('R2 json5: syntax features', () => {
  assert.deepEqual(parse("// c\n{/* x */ 'a': 'b\\x41\\u0042', $k_1: +.5, h: 0xFF, n: -Infinity, t: [true,null,],}"),
    { a: 'bAB', $k_1: 0.5, h: 255, n: -Infinity, t: [true, null] });
  assert.ok(Number.isNaN(parse('NaN')));
  assert.equal(parse('"a\\\nb"'), 'ab');
  assert.equal(parse('5.'), 5);
  assert.equal(parse('1e3'), 1000);
  assert.deepEqual(parse('{"__proto__": 1}') && Object.keys(parse('{"__proto__": 1}')), ['__proto__']);
});

test('R2 json5: plain JSON is accepted unchanged', () => {
  const o = { a: [1, 2.5, -3e2, 'x\ny', null, false], b: { c: {} } };
  assert.deepEqual(parse(JSON.stringify(o)), o);
});

test('R2 json5: errors', () => {
  for (const bad of ['', '{', '{a:}', '[1 2]', '{"a":1} x', "'abc", '/* x', '{a 1}', '"\\xZZ"', 'tru']) {
    assert.throws(() => parse(bad), SyntaxError, bad);
  }
});

test('R17 json5: deep nesting and long arrays parse quickly', () => {
  const t0 = Date.now();
  const arr = parse('[' + '1,'.repeat(200000) + ']');
  assert.equal(arr.length, 200000);
  assert.equal(parse('['.repeat(1000) + ']'.repeat(1000)).length, 1);
  assert.ok(Date.now() - t0 < 2000);
});
