'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { start, README_DB } = require('./helper');

const PEOPLE = {
  people: [
    { id: '1', name: 'Bob', age: 25, city: 'Paris', active: true, author: { name: 'carl' } },
    { id: '2', name: 'alice', age: 30, city: 'berlin', active: false, author: { name: 'Anna' } },
    { id: '3', name: 'Charlie', age: 35, city: 'Paris', active: true, author: { name: 'bob' } },
    { id: '4', name: 'dave', age: 9, city: 'Rome', active: false, author: { name: 'Zoe' } },
    { id: '5', name: 'Eve', age: 30 },
  ],
};
const ids = (r) => (r.json.data || r.json).map((x) => x.id);

let readme, people;
test.before(async () => { readme = await start(); people = await start(PEOPLE); });
test.after(async () => { await readme.stop(); await people.stop(); });

test('R1 startup banner', () => {
  assert.match(readme.out(), /^JSON Server started on PORT :\d+\nhttp:\/\/127\.0\.0\.1:\d+\n/);
});

test('R4 README: GET /posts/1 exact body', async () => {
  const r = await readme.get('/posts/1');
  assert.equal(r.status, 200);
  assert.equal(r.raw, '{\n  "id": "1",\n  "title": "a title",\n  "views": 100\n}');
  assert.match(r.headers.get('content-type'), /^application\/json/);
});

test('R4 GET collection, unknown id, unknown route, 404 body', async () => {
  const r = await readme.get('/posts');
  assert.equal(r.status, 200);
  assert.deepEqual(r.json, README_DB.posts);
  assert.ok(r.raw.startsWith('[\n  {\n    "id": "1"'));
  for (const p of ['/posts/99', '/nope', '/nope/1', '/posts/1/x', '/']) {
    const n = await readme.get(p);
    assert.equal(n.status, 404, p);
    assert.deepEqual(n.json, { error: 'Not Found' });
  }
});

test('R6 singular GET + wrong methods', async () => {
  assert.deepEqual((await readme.get('/profile')).json, { name: 'typicode' });
  assert.equal((await readme.req('DELETE', '/profile')).status, 404);
  assert.equal((await readme.req('POST', '/profile', {})).status, 404);
  assert.equal((await readme.req('POST', '/posts/1', {})).status, 404);
  assert.equal((await readme.req('DELETE', '/posts')).status, 404);
  assert.equal((await readme.get('/$schema')).status, 404);
});

// ---- conditions (R8)
test('R8 README condition examples', async () => {
  assert.deepEqual(ids(await readme.get('/posts?views:gt=100')), ['2']);
  assert.deepEqual(ids(await readme.get('/posts?title:eq=another%20title')), ['2']);
  assert.deepEqual(ids(await readme.get('/posts?id:in=1,2,3')), ['1', '2']);
  assert.deepEqual(ids(await readme.get('/posts?title:contains=ANOTHER')), ['2']);
  assert.deepEqual(ids(await readme.get('/posts?title:startsWith=A%20T')), ['1']);
  assert.deepEqual(ids(await readme.get('/posts?title:endsWith=TITLE')), ['1', '2']);
  assert.deepEqual(ids(await readme.get('/posts?views=100')), ['1']);
});

test('R8 operators on mixed-type data', async () => {
  const q = async (s) => ids(await people.get('/people?' + s));
  assert.deepEqual(await q('age:gt=25'), ['2', '3', '5']); // numeric, not string, comparison (9 < 25)
  assert.deepEqual(await q('age:gte=30'), ['2', '3', '5']);
  assert.deepEqual(await q('age:lt=30'), ['1', '4']);
  assert.deepEqual(await q('age:lte=30'), ['1', '2', '4', '5']);
  assert.deepEqual(await q('age:ne=30'), ['1', '3', '4']);
  assert.deepEqual(await q('age:eq=30'), ['2', '5']);
  assert.deepEqual(await q('active=true'), ['1', '3']);
  assert.deepEqual(await q('active:ne=true'), ['2', '4', '5']);
  assert.deepEqual(await q('city:in=Paris,Rome'), ['1', '3', '4']);
  assert.deepEqual(await q('age:in=9,35'), ['3', '4']);
  assert.deepEqual(await q('name:contains=LI'), ['2', '3']);
  assert.deepEqual(await q('name:startsWith=b'), ['1']);
  assert.deepEqual(await q('name:endsWith=IE'), ['3']);
  assert.deepEqual(await q('author.name=Anna'), ['2']);
  assert.deepEqual(await q('author.name:lt=b'), ['2', '4']); // plain string order: 'Zoe' < 'b'
  assert.deepEqual(await q('city=Paris&age:gt=30'), ['3']); // AND
  assert.deepEqual(await q('city=nowhere'), []);
  assert.deepEqual(await q('age=abc'), []);
});

// ---- sort (R9)
test('R9 sorting', async () => {
  const q = async (s) => ids(await people.get('/people?_sort=' + s));
  assert.deepEqual(await q('name'), ['2', '1', '3', '4', '5']); // case-insensitive
  assert.deepEqual(await q('-name'), ['5', '4', '3', '1', '2']);
  assert.deepEqual(await q('-age'), ['3', '2', '5', '1', '4']); // numeric, stable on ties
  assert.deepEqual(await q('age'), ['4', '1', '2', '5', '3']);
  assert.deepEqual(await q('city,-age'), ['2', '3', '1', '4', '5']); // missing last
  assert.deepEqual(await q('author.name'), ['2', '3', '1', '4', '5']);
  assert.deepEqual(ids(await readme.get('/posts?_sort=-views')), ['2', '1']);
});

// ---- pagination (R10)
test('R10 pagination envelope', async () => {
  const r = await people.get('/people?_page=1&_per_page=2');
  assert.deepEqual(Object.keys(r.json), ['first', 'prev', 'next', 'last', 'pages', 'items', 'data']);
  assert.deepEqual({ ...r.json, data: undefined }, { first: 1, prev: null, next: 2, last: 3, pages: 3, items: 5, data: undefined });
  assert.deepEqual(ids(r), ['1', '2']);
  const p3 = await people.get('/people?_page=3&_per_page=2');
  assert.equal(p3.json.prev, 2); assert.equal(p3.json.next, null);
  assert.deepEqual(ids(p3), ['5']);
  const mid = await people.get('/people?_page=2&_per_page=2');
  assert.equal(mid.json.prev, 1); assert.equal(mid.json.next, 3);
});

test('R10 pagination defaults, normalization, composition', async () => {
  const d = await people.get('/people?_page=1');
  assert.equal(d.json.pages, 1); assert.equal(d.json.items, 5); assert.equal(d.json.data.length, 5);
  assert.equal((await people.get('/people?_page=99&_per_page=2')).json.data[0].id, '5'); // clamped
  assert.equal((await people.get('/people?_page=0&_per_page=2')).json.prev, null);
  assert.equal((await people.get('/people?_page=x&_per_page=-4')).json.pages, 1);
  assert.deepEqual(ids(await people.get('/people?_per_page=2')), ['1', '2']);
  const f = await people.get('/people?city=Paris&_sort=-age&_page=1&_per_page=1');
  assert.equal(f.json.items, 2); assert.equal(f.json.pages, 2); assert.deepEqual(ids(f), ['3']);
  const e = await people.get('/people?city=none&_page=1');
  assert.deepEqual(e.json, { first: 1, prev: null, next: null, last: 1, pages: 1, items: 0, data: [] });
});

// ---- embed (R11)
test('R11 embed children and parents', async () => {
  const r = await readme.get('/posts?_embed=comments');
  assert.deepEqual(r.json, [
    { ...README_DB.posts[0], comments: README_DB.comments },
    { ...README_DB.posts[1], comments: [] },
  ]);
  const c = await readme.get('/comments?_embed=post');
  assert.deepEqual(c.json[0], { ...README_DB.comments[0], post: README_DB.posts[0] });
  assert.equal(c.json.length, 2);
  const one = await readme.get('/posts/1?_embed=comments');
  assert.equal(one.json.comments.length, 2);
  assert.equal((await readme.get('/posts/2?_embed=comments')).json.comments.length, 0);
  assert.deepEqual(Object.keys((await readme.get('/posts?_embed=bogus')).json[0]), ['id', 'title', 'views']);
  const pg = await readme.get('/posts?_embed=comments&_page=1&_per_page=1');
  assert.equal(pg.json.data[0].comments.length, 2);
  assert.equal((await readme.get('/posts')).json[0].comments, undefined); // not persisted/leaked
});

// ---- _where (R12)
test('R12 _where', async () => {
  const w = (o) => people.get('/people?_where=' + encodeURIComponent(JSON.stringify(o)));
  assert.deepEqual(ids(await w({ or: [{ age: { gt: 30 } }, { author: { name: { lt: 'b' } } }] })), ['2', '3', '4']);
  assert.deepEqual(ids(await w({ and: [{ city: 'Paris' }, { not: { active: false } }] })), ['1', '3']);
  assert.deepEqual(ids(await w({ not: { city: 'Paris' } })), ['2', '4', '5']);
  assert.deepEqual(ids(await w({ age: { gte: 25, lt: 35 }, city: { in: ['Paris', 'berlin'] } })), ['1', '2']);
  assert.deepEqual(ids(await w({ name: { startsWith: 'AL' } })), ['2']);
  assert.deepEqual(ids(await people.get('/people?name=zzz&_where=' + encodeURIComponent('{"city":"Rome"}'))), ['4']); // overrides
  assert.deepEqual(ids(await people.get('/people?city=Rome&_where={bad')), ['4']); // invalid -> ignored
  assert.deepEqual(ids(await people.get('/people?_sort=-age&_page=1&_per_page=1&_where=' + encodeURIComponent('{"age":{"gt":10}}'))), ['3']);
});

test('R12 README _where example on README db', async () => {
  const q = '{"or":[{"views":{"gt":100}},{"author":{"name":{"lt":"m"}}}]}';
  assert.deepEqual(ids(await readme.get('/posts?_where=' + q)), ['2']);
});

// ---- mutations (R5-R7, R13)
test('R5/R6/R7 mutations and persistence', async () => {
  const s = await start();
  try {
    const seen = new Set();
    for (let i = 0; i < 20; i++) {
      const r = await s.req('POST', '/posts', { id: 'mine', title: 't' + i });
      assert.equal(r.status, 201);
      assert.notEqual(r.json.id, 'mine');
      assert.equal(typeof r.json.id, 'string');
      assert.equal(Object.keys(r.json)[0], 'id');
      assert.ok(!seen.has(r.json.id)); seen.add(r.json.id);
    }
    assert.equal(s.disk().posts.length, 22);
    const id = [...seen][0];
    let r = await s.req('PUT', `/posts/${id}`, { id: 'zzz', title: 'new' });
    assert.deepEqual(r.json, { id, title: 'new' });
    r = await s.req('PATCH', '/posts/1', { views: 101, id: 'q' });
    assert.deepEqual(r.json, { id: '1', title: 'a title', views: 101 });
    r = await s.req('PUT', '/profile', { x: 1 });
    assert.deepEqual(r.json, { x: 1 });
    r = await s.req('PATCH', '/profile', { y: 2 });
    assert.deepEqual(r.json, { x: 1, y: 2 });
    assert.equal((await s.req('PUT', '/posts/nope', {})).status, 404);
    assert.equal((await s.req('PATCH', '/posts/nope', {})).status, 404);
    assert.equal((await s.req('POST', '/posts', '{bad')).status, 400);
    assert.equal((await s.req('POST', '/posts', '[1]')).status, 400);
    assert.equal((await s.req('PATCH', '/profile', '"s"')).status, 400);
    r = await s.req('DELETE', `/posts/${id}`);
    assert.equal(r.status, 200); assert.equal(r.json.title, 'new');
    assert.equal((await s.get(`/posts/${id}`)).status, 404);
    assert.equal((await s.req('DELETE', `/posts/${id}`)).status, 404);
    const disk = s.disk();
    assert.equal(disk.posts.length, 21);
    assert.deepEqual(disk.profile, { x: 1, y: 2 });
    assert.equal(fs.readFileSync(s.dbFile, 'utf8').startsWith('{\n  "posts": ['), true);
    assert.deepEqual(fs.readdirSync(s.dir), ['db.json']); // no temp files left
    // restart: state survives
    await s.stop();
    const s2 = await start(null, { dir: s.dir });
    try {
      assert.equal((await s2.get('/posts')).json.length, 21);
      assert.equal((await s2.get('/posts/1')).json.views, 101);
      assert.deepEqual((await s2.get('/profile')).json, { x: 1, y: 2 });
    } finally { await s2.stop(); }
  } finally { await s.stop().catch(() => {}); }
});

test('R7 delete without _dependent nulls foreign keys', async () => {
  const s = await start();
  try {
    const r = await s.req('DELETE', '/posts/1');
    assert.equal(r.status, 200);
    assert.deepEqual((await s.get('/comments')).json, [
      { id: '1', text: 'a comment about post 1', postId: null },
      { id: '2', text: 'another comment about post 1', postId: null },
    ]);
    assert.deepEqual(s.disk().comments.map((c) => c.postId), [null, null]);
    assert.equal(s.disk().posts.length, 1);
  } finally { await s.stop(); }
});

test('R7 README: DELETE /posts/1?_dependent=comments cascades', async () => {
  const s = await start({ ...README_DB, comments: [...README_DB.comments, { id: '3', text: 'other', postId: '2' }] });
  try {
    const r = await s.req('DELETE', '/posts/1?_dependent=comments');
    assert.equal(r.status, 200);
    assert.deepEqual((await s.get('/comments')).json, [{ id: '3', text: 'other', postId: '2' }]);
    assert.deepEqual(s.disk().comments.length, 1);
  } finally { await s.stop(); }
});

test('R7 _dependent only affects listed collections; irregular plural', async () => {
  const s = await start({
    categories: [{ id: 'c1' }], items: [{ id: 'i1', categoryId: 'c1' }], notes: [{ id: 'n1', categoryId: 'c1' }],
  });
  try {
    await s.req('DELETE', '/categories/c1?_dependent=items');
    assert.deepEqual(s.disk().items, []);
    assert.deepEqual(s.disk().notes, [{ id: 'n1', categoryId: null }]);
  } finally { await s.stop(); }
});

test('R3/R5 numeric ids in file are addressable, preserved on disk', async () => {
  const s = await start({ things: [{ id: 7, n: 1 }], meta: 5, list: 'x' });
  try {
    assert.equal((await s.get('/things/7')).json.n, 1);
    assert.equal((await s.get('/meta')).status, 404);
    assert.equal((await s.req('PATCH', '/things/7', { n: 2 })).json.id, 7);
    assert.equal((await s.get('/things?id=7')).json.length, 1);
  } finally { await s.stop(); }
});

test('R2 json5 db file and $schema key', async () => {
  const s = await start({}, {
    file: 'db.json5',
    text: `// comment
{
  "$schema": "./schema.json",
  posts: [ { id: "1", title: 'single', views: 0x10, }, ],
  profile: { name: "typicode" },
}`,
  });
  try {
    assert.deepEqual((await s.get('/posts/1')).json, { id: '1', title: 'single', views: 16 });
    assert.equal((await s.get('/$schema')).status, 404);
    await s.req('POST', '/posts', { title: 'x' });
    const disk = s.disk();
    assert.equal(disk.$schema, './schema.json');
    assert.equal(disk.posts.length, 2);
  } finally { await s.stop(); }
});

test('R14 CORS headers and preflight', async () => {
  const r = await readme.get('/posts');
  assert.equal(r.headers.get('access-control-allow-origin'), '*');
  assert.equal((await readme.get('/nope')).headers.get('access-control-allow-origin'), '*');
  const o = await fetch(readme.base + '/posts', {
    method: 'OPTIONS', headers: { Origin: 'http://x.test', 'Access-Control-Request-Method': 'PATCH', 'Access-Control-Request-Headers': 'x-foo, content-type' },
  });
  assert.equal(o.status, 204);
  assert.equal(o.headers.get('access-control-allow-origin'), '*');
  assert.match(o.headers.get('access-control-allow-methods'), /PATCH/);
  assert.equal(o.headers.get('access-control-allow-headers'), 'x-foo, content-type');
});

test('R16 HEAD requests', async () => {
  const r = await fetch(readme.base + '/posts/1', { method: 'HEAD' });
  assert.equal(r.status, 200);
  assert.equal(await r.text(), '');
  assert.equal((await fetch(readme.base + '/posts/9', { method: 'HEAD' })).status, 404);
});

test('R16 concurrent mutations all persist', async () => {
  const s = await start({ xs: [] });
  try {
    const rs = await Promise.all(Array.from({ length: 60 }, (_, i) => s.req('POST', '/xs', { i })));
    assert.ok(rs.every((r) => r.status === 201));
    assert.equal(s.disk().xs.length, 60);
    assert.equal(new Set(rs.map((r) => r.json.id)).size, 60);
  } finally { await s.stop(); }
});

// ---- static (R15)
test('R15 static files via --static and ./public default', async () => {
  const { tmpDir } = require('./helper');
  const dir = tmpDir();
  fs.mkdirSync(path.join(dir, 'static'));
  fs.mkdirSync(path.join(dir, 'public'));
  fs.writeFileSync(path.join(dir, 'static', 'index.html'), '<h1>hi</h1>');
  fs.writeFileSync(path.join(dir, 'static', 'a.css'), 'body{}');
  fs.writeFileSync(path.join(dir, 'public', 'p.txt'), 'pub');
  fs.writeFileSync(path.join(dir, 'secret.txt'), 'nope');
  const s = await start(README_DB, { dir, args: ['--static', path.join(dir, 'static')] });
  try {
    let r = await s.get('/');
    assert.equal(r.status, 200); assert.equal(r.raw, '<h1>hi</h1>');
    assert.match(r.headers.get('content-type'), /^text\/html/);
    r = await s.get('/a.css');
    assert.match(r.headers.get('content-type'), /^text\/css/);
    assert.equal((await s.get('/p.txt')).raw, 'pub'); // default ./public
    assert.equal((await s.get('/posts/1')).json.id, '1'); // API unaffected
    assert.equal((await s.get('/missing.html')).status, 404);
    assert.equal((await s.get('/..%2fsecret.txt')).status, 404);
    assert.equal((await s.get('/%2e%2e/secret.txt')).status, 404);
    const raw = await new Promise((resolve) => {
      const sock = require('node:net').connect(+new URL(s.base).port, '127.0.0.1', () => sock.write('GET /../secret.txt HTTP/1.0\r\n\r\n'));
      let d = ''; sock.on('data', (c) => { d += c; }); sock.on('end', () => resolve(d));
    });
    assert.match(raw, /^HTTP\/1.1 404/);
  } finally { await s.stop(); }
});

test('R2 a .json file containing JSON5 syntax still loads', async () => {
  const s = await start({}, { text: "{ posts: [ { id: '1', t: 1, }, ], }" });
  try { assert.deepEqual((await s.get('/posts/1')).json, { id: '1', t: 1 }); } finally { await s.stop(); }
});

test('R4/R10 filter+sort+_embed on single and empty collections', async () => {
  const s = await start({ posts: [], profile: {} });
  try {
    assert.deepEqual((await s.get('/posts?_sort=-views&title:gt=a')).json, []);
    assert.deepEqual((await s.get('/profile')).json, {});
  } finally { await s.stop(); }
});
