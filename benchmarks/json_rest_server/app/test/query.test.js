'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { start } = require('./helpers');

const DB = {
  posts: [
    { id: '1', title: 'Hello World', views: 100, draft: false, author: { name: 'typicode' }, userId: '1' },
    { id: '2', title: 'hello again', views: 200, draft: true, author: { name: 'zed' } },
    { id: '3', title: 'Goodbye world', views: 50, draft: false, author: { name: 'anna' }, tag: null },
    { id: '10', title: 'Ten', views: 1000, draft: false, author: { name: 'mike' } },
  ],
  comments: [
    { id: '1', text: 'c1', postId: '1' },
    { id: '2', text: 'c2', postId: '1' },
    { id: '3', text: 'c3', postId: '2' },
    { id: '4', text: 'orphan' },
  ],
  categories: [{ id: 'a', name: 'A' }],
  items: [{ id: 'x', categoryId: 'a' }, { id: 'y', categoryId: 'zz' }],
  profile: { name: 'p' },
};
let s;
test.before(async () => { s = await start(DB); });
test.after(async () => { await s.close(); });
const ids = async (u) => (await s.get(u)).json.map((x) => x.id);

test('R12 README condition examples', async () => {
  assert.deepEqual(await ids('/posts?views:gt=100'), ['2', '10']);
  assert.deepEqual(await ids('/posts?title:eq=Ten'), ['10']);
  assert.deepEqual(await ids('/posts?id:in=1,2,3'), ['1', '2', '3']);
  assert.deepEqual(await ids('/posts?author.name:eq=typicode'), ['1']);
  assert.deepEqual(await ids('/posts?title:contains=hello'), ['1', '2']);
  assert.deepEqual(await ids('/posts?title:startsWith=hello'), ['1', '2']);
  assert.deepEqual(await ids('/posts?title:endsWith=WORLD'), ['1', '3']);
});

test('R12 all comparison operators and implicit eq', async () => {
  assert.deepEqual(await ids('/posts?views=100'), ['1']);
  assert.deepEqual(await ids('/posts?views:ne=100'), ['2', '3', '10']);
  assert.deepEqual(await ids('/posts?views:lt=100'), ['3']);
  assert.deepEqual(await ids('/posts?views:lte=100'), ['1', '3']);
  assert.deepEqual(await ids('/posts?views:gte=200'), ['2', '10']);
  assert.deepEqual(await ids('/posts?views:gt=50&views:lt=1000'), ['1', '2']);
});

test('R13 type-aware: numbers numeric (not lexicographic), booleans, null, strings', async () => {
  assert.deepEqual(await ids('/posts?views:gt=99'), ['1', '2', '10']);
  assert.deepEqual(await ids('/posts?views:gt=9'), ['1', '2', '3', '10']);
  assert.deepEqual(await ids('/posts?draft=true'), ['2']);
  assert.deepEqual(await ids('/posts?draft:eq=false'), ['1', '3', '10']);
  assert.deepEqual(await ids('/posts?tag=null'), ['3']);
  assert.deepEqual(await ids('/posts?author.name:lt=m'), ['3']);
  assert.deepEqual(await ids('/posts?views=abc'), []);
  assert.deepEqual(await ids('/posts?title:gt=5'), ['1', '2', '3', '10']);
});

test('R13 missing field: only ne matches; unknown operator ignored', async () => {
  assert.deepEqual(await ids('/posts?userId=1'), ['1']);
  assert.deepEqual(await ids('/posts?userId:ne=1'), ['2', '3', '10']);
  assert.equal((await ids('/posts?views:bogus=1')).length, 4);
});

test('R14 sort asc/desc/multi/nested/numeric', async () => {
  assert.deepEqual(await ids('/posts?_sort=views'), ['3', '1', '2', '10']);
  assert.deepEqual(await ids('/posts?_sort=-views'), ['10', '2', '1', '3']);
  assert.deepEqual(await ids('/posts?_sort=title'), ['3', '1', '10', '2']); // code-point order
  assert.deepEqual(await ids('/posts?_sort=author.name,-views'), ['3', '10', '1', '2']);
  assert.deepEqual(await ids('/posts?_sort=draft,-views'), ['10', '1', '3', '2']);
});

test('R14 missing values sort last in both directions', async () => {
  assert.deepEqual(await ids('/posts?_sort=userId'), ['1', '2', '3', '10']);
  assert.deepEqual(await ids('/posts?_sort=-userId'), ['1', '2', '3', '10']);
});

test('R15 README pagination envelope', async () => {
  const r = (await s.get('/posts?_page=1&_per_page=3')).json;
  assert.deepEqual(Object.keys(r), ['first', 'prev', 'next', 'last', 'pages', 'items', 'data']);
  assert.equal(r.first, 1); assert.equal(r.prev, null); assert.equal(r.next, 2);
  assert.equal(r.last, 2); assert.equal(r.pages, 2); assert.equal(r.items, 4);
  assert.deepEqual(r.data.map((x) => x.id), ['1', '2', '3']);
  const r2 = (await s.get('/posts?_page=2&_per_page=3')).json;
  assert.equal(r2.prev, 1); assert.equal(r2.next, null);
  assert.deepEqual(r2.data.map((x) => x.id), ['10']);
});

test('R15 defaults and normalization', async () => {
  let r = (await s.get('/posts?_page=1')).json;
  assert.equal(r.items, 4); assert.equal(r.pages, 1); assert.equal(r.data.length, 4);
  r = (await s.get('/posts?_per_page=2')).json;
  assert.equal(r.pages, 2); assert.deepEqual(r.data.map((x) => x.id), ['1', '2']);
  r = (await s.get('/posts?_page=0&_per_page=-5')).json;
  assert.equal(r.data.length, 4); assert.equal(r.prev, null);
  r = (await s.get('/posts?_page=abc&_per_page=x')).json;
  assert.equal(r.data.length, 4);
  r = (await s.get('/posts?_page=99&_per_page=3')).json;
  assert.equal(r.next, null); assert.equal(r.prev, 1); assert.deepEqual(r.data.map((x) => x.id), ['10']);
});

test('R15 filter and sort apply before pagination; empty result', async () => {
  let r = (await s.get('/posts?views:gt=60&_sort=-views&_per_page=2&_page=2')).json;
  assert.equal(r.items, 3); assert.deepEqual(r.data.map((x) => x.id), ['1']);
  r = (await s.get('/posts?views:gt=99999&_page=1')).json;
  assert.deepEqual(r, { first: 1, prev: null, next: null, last: 1, pages: 1, items: 0, data: [] });
});

test('R16 _embed children and parents, single item, multiple, unknown', async () => {
  let r = (await s.get('/posts?_embed=comments')).json;
  assert.deepEqual(r[0].comments.map((c) => c.id), ['1', '2']);
  assert.deepEqual(r[1].comments.map((c) => c.id), ['3']);
  assert.deepEqual(r[2].comments, []);
  r = (await s.get('/comments?_embed=post')).json;
  assert.equal(r[0].post.title, 'Hello World');
  assert.equal(r[2].post.id, '2');
  assert.equal(r[3].post, null);
  r = (await s.get('/posts/1?_embed=comments')).json;
  assert.equal(r.comments.length, 2);
  r = (await s.get('/items?_embed=category')).json;
  assert.equal(r[0].category.name, 'A'); assert.equal(r[1].category, null);
  r = (await s.get('/posts/1?_embed=comments&_embed=nothing')).json;
  assert.equal(r.nothing, undefined);
  r = (await s.get('/posts/1?_embed=comments,nothing')).json;
  assert.equal(r.comments.length, 2);
  r = (await s.get('/posts?_embed=comments&_page=1&_per_page=1')).json;
  assert.equal(r.data[0].comments.length, 2);
});

test('R16 embeds are not persisted', async () => {
  await s.get('/posts?_embed=comments');
  assert.equal(s.disk().posts[0].comments, undefined);
});

test('R17 README _where example', async () => {
  const w = encodeURIComponent('{"or":[{"views":{"gt":100}},{"author":{"name":{"lt":"m"}}}]}');
  // views>100 -> 2,10 ; author.name < "m" -> 1(typicode? no),3 anna  => 2,3,10
  assert.deepEqual(await ids('/posts?_where=' + w), ['2', '3', '10']);
});

test('R17 _where and/not/in/direct equality, overrides params, invalid ignored', async () => {
  const q = (o) => '/posts?_where=' + encodeURIComponent(JSON.stringify(o));
  assert.deepEqual(await ids(q({ and: [{ views: { gte: 100 } }, { draft: { eq: false } }] })), ['1', '10']);
  assert.deepEqual(await ids(q({ not: { views: { gt: 100 } } })), ['1', '3']);
  assert.deepEqual(await ids(q({ id: { in: ['1', '3'] } })), ['1', '3']);
  assert.deepEqual(await ids(q({ views: 200 })), ['2']);
  assert.deepEqual(await ids(q({ title: { contains: 'WORLD' } })), ['1', '3']);
  assert.deepEqual(await ids(q({ views: { gt: 100 } }) + '&views:lt=100'), ['2', '10']);
  assert.deepEqual(await ids('/posts?_where=%7Bbroken&views:gt=100'), ['2', '10']);
  assert.deepEqual(await ids('/posts?_where=' + encodeURIComponent('{"and":5}') + '&views:gt=100'), ['2', '10']);
  assert.deepEqual(await ids(q({ views: { gt: 50 } }) + '&_sort=-views'), ['10', '2', '1']);
});

test('R21 perf: 10k items filter+sort+paginate+embed fast', async () => {
  const big = { posts: [], comments: [] };
  for (let i = 0; i < 10000; i++) {
    big.posts.push({ id: String(i), n: (i * 7919) % 10007, title: 'T' + i, author: { name: 'a' + (i % 50) } });
    big.comments.push({ id: String(i), postId: String(i) });
  }
  const b = await start(big);
  try {
    const t = Date.now();
    const r = await b.get('/posts?n:gt=100&author.name:startsWith=a1&_sort=-n,title&_embed=comments&_page=2&_per_page=20');
    const r2 = await b.get('/posts?_where=' + encodeURIComponent('{"or":[{"n":{"lt":50}},{"title":{"contains":"99"}}]}'));
    assert.equal(r.status, 200); assert.equal(r2.status, 200);
    assert.equal(r.json.data.length, 20);
    assert.ok(Date.now() - t < 2000, `took ${Date.now() - t}ms`);
  } finally { await b.close(); }
});
