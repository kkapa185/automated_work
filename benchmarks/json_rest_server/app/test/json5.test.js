'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { parse } = require('../src/json5');

test('R2 README db.json5 example', () => {
  const t = `{
  posts: [
    { id: "1", title: "a title", views: 100 },
    { id: "2", title: "another title", views: 200 },
  ],
  comments: [
    { id: "1", text: "a comment about post 1", postId: "1" },
    { id: "2", text: "another comment about post 1", postId: "1" },
  ],
  profile: {
    name: "typicode",
  },
}`;
  const v = parse(t);
  assert.deepEqual(v.posts[1], { id: '2', title: 'another title', views: 200 });
  assert.deepEqual(v.profile, { name: 'typicode' });
  assert.equal(v.comments.length, 2);
});

test('R2 JSON5 features', () => {
  assert.deepEqual(parse("// c\n{ /* x */ a: 'it\\'s', 'b-c': 0x1F, d: +.5, e: -Infinity, f: [1,2,], g: \"l1\\\nl2\", h: 5., $i_: null, t: true }"),
    { a: "it's", 'b-c': 31, d: 0.5, e: -Infinity, f: [1, 2], g: 'l1l2', h: 5, $i_: null, t: true });
  assert.ok(Number.isNaN(parse('NaN')));
  assert.equal(parse('"\\x41\\u0042\\0"'), 'AB\0');
  assert.equal(parse('1e3'), 1000);
  assert.deepEqual(parse('{"__proto__": 1}') && Object.keys(parse('{"__proto__": 1}')), ['__proto__']);
  assert.equal(({}).polluted, undefined);
});

test('R2 invalid JSON5 throws', () => {
  for (const t of ['', '{', '{a:}', '[1 2]', '{"a":1} x', "'abc", '/* x', '{a:1,,}', 'tru', '"a\nb"']) {
    assert.throws(() => parse(t), SyntaxError, JSON.stringify(t));
  }
});

test('R21 deep nesting / long input parses in reasonable time', () => {
  const t = Date.now();
  const arr = '['.repeat(2000) + ']'.repeat(2000);
  parse(arr);
  parse('[' + Array.from({ length: 100000 }, (_, i) => i).join(',') + ']');
  assert.ok(Date.now() - t < 2000);
});
