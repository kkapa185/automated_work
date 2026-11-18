'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { start } = require('./helper');

test('R17 10k-item collection: filter + sort + embed + page under 1s', async () => {
  const N = 10000;
  const posts = Array.from({ length: N }, (_, i) => ({ id: String(i), title: `Title ${(i * 7919) % N}`, views: (i * 31) % 1000, author: { name: `n${i % 50}` } }));
  const comments = Array.from({ length: N }, (_, i) => ({ id: String(i), postId: String(i % N) }));
  const s = await start({ posts, comments });
  try {
    const t0 = Date.now();
    const r = await s.get('/posts?views:gt=100&title:contains=title&_sort=author.name,-views,title&_embed=comments&_page=3&_per_page=50');
    const dt = Date.now() - t0;
    assert.equal(r.status, 200);
    assert.equal(r.json.data.length, 50);
    assert.equal(r.json.data[0].comments.length, 1);
    assert.ok(dt < 1000, `took ${dt}ms`);
    const t1 = Date.now();
    const all = await s.get('/posts?_embed=comments&_where=' + encodeURIComponent('{"or":[{"views":{"gt":500}},{"not":{"author":{"name":"n1"}}}]}'));
    assert.equal(all.status, 200);
    assert.ok(Date.now() - t1 < 2000);
  } finally { await s.stop(); }
});

test('R17 200 sequential POSTs complete quickly', async () => {
  const s = await start({ xs: [] });
  try {
    const t0 = Date.now();
    for (let i = 0; i < 200; i++) assert.equal((await s.req('POST', '/xs', { i })).status, 201);
    assert.ok(Date.now() - t0 < 10000);
    assert.equal(s.disk().xs.length, 200);
  } finally { await s.stop(); }
});
