'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { start, README_DB } = require('./helpers');

let s;
test.beforeEach(async () => { s = await start(); });
test.afterEach(async () => { await s.close(); });

test('R5 README: GET /posts/1 exact pretty body', async () => {
  const r = await s.get('/posts/1');
  assert.equal(r.status, 200);
  assert.equal(r.text, '{\n  "id": "1",\n  "title": "a title",\n  "views": 100\n}');
  assert.match(r.headers.get('content-type'), /^application\/json/);
});

test('R4 GET collection and object resource', async () => {
  const r = await s.get('/posts');
  assert.deepEqual(r.json, README_DB.posts);
  assert.deepEqual((await s.get('/profile')).json, { name: 'typicode' });
});

test('R9 404 NotFound for unknown route, resource, id, extra segments', async () => {
  for (const u of ['/nope', '/posts/99', '/posts/1/comments', '/profile/1', '/']) {
    const r = await s.get(u);
    assert.equal(r.status, 404, u);
    assert.equal(r.text, '{\n  "error": "NotFound"\n}');
  }
  assert.equal((await s.req('DELETE', '/nope/1')).status, 404);
  assert.equal((await s.req('PUT', '/posts/99', { a: 1 })).status, 404);
  assert.equal((await s.req('POST', '/profile', { a: 1 })).status, 404);
  assert.equal((await s.req('DELETE', '/profile')).status, 404);
});

test('R6 POST generates unique string id, 201, persisted', async () => {
  const a = await s.req('POST', '/posts', { title: 'x', views: 1 });
  const b = await s.req('POST', '/posts', { title: 'y' });
  assert.equal(a.status, 201);
  assert.equal(typeof a.json.id, 'string');
  assert.ok(a.json.id.length > 0);
  assert.notEqual(a.json.id, b.json.id);
  assert.equal(a.json.title, 'x');
  assert.equal((await s.get('/posts/' + a.json.id)).json.views, 1);
  assert.equal(s.disk().posts.length, 4);
});

test('R6 POST with explicit id (numeric coerced to string); duplicate -> 400', async () => {
  const a = await s.req('POST', '/posts', { id: 77, title: 'n' });
  assert.equal(a.status, 201);
  assert.equal(a.json.id, '77');
  assert.equal((await s.get('/posts/77')).status, 200);
  assert.equal((await s.req('POST', '/posts', { id: '77' })).status, 400);
});

test('R7 PUT replaces, keeps URL id', async () => {
  const r = await s.req('PUT', '/posts/1', { id: 'zzz', title: 'new' });
  assert.equal(r.status, 200);
  assert.deepEqual(r.json, { id: '1', title: 'new' });
  assert.deepEqual(s.disk().posts[0], { id: '1', title: 'new' });
});

test('R7 PATCH merges', async () => {
  const r = await s.req('PATCH', '/posts/2', { views: 5, id: 'bad' });
  assert.equal(r.status, 200);
  assert.deepEqual(r.json, { id: '2', title: 'another title', views: 5 });
});

test('R7 object resource PUT / PATCH', async () => {
  let r = await s.req('PATCH', '/profile', { age: 3 });
  assert.deepEqual(r.json, { name: 'typicode', age: 3 });
  r = await s.req('PUT', '/profile', { name: 'x' });
  assert.deepEqual(r.json, { name: 'x' });
  assert.deepEqual(s.disk().profile, { name: 'x' });
});

test('R7 bad bodies -> 400 JSON error', async () => {
  for (const body of ['{oops', '[1]', '"s"', '']) {
    const r = await s.req('POST', '/posts', body);
    assert.equal(r.status, 400, body);
    assert.ok(r.json.error);
  }
  assert.equal((await s.req('PATCH', '/profile', '[]')).status, 400);
});

test('R8 DELETE returns deleted item and persists', async () => {
  const r = await s.req('DELETE', '/posts/1');
  assert.equal(r.status, 200);
  assert.equal(r.json.id, '1');
  assert.equal((await s.get('/posts/1')).status, 404);
  assert.equal(s.disk().posts.length, 1);
  assert.equal((await s.req('DELETE', '/posts/1')).status, 404);
});

test('R18 DELETE ?_dependent=comments cascades', async () => {
  await s.req('POST', '/comments', { id: '3', text: 'other', postId: '2' });
  const r = await s.req('DELETE', '/posts/1?_dependent=comments');
  assert.equal(r.status, 200);
  const d = s.disk();
  assert.deepEqual(d.comments.map((c) => c.id), ['3']);
  assert.deepEqual(d.posts.map((p) => p.id), ['2']);
});

test('R18 DELETE without _dependent keeps comments; unknown dependent ignored', async () => {
  await s.req('DELETE', '/posts/1?_dependent=nothing');
  assert.equal(s.disk().comments.length, 2);
});

test('R11 CORS headers and preflight', async () => {
  const r = await s.get('/posts');
  assert.equal(r.headers.get('access-control-allow-origin'), '*');
  const p = await s.req('OPTIONS', '/posts/1', undefined, {
    'Access-Control-Request-Method': 'PATCH', 'Access-Control-Request-Headers': 'content-type,x-foo',
  });
  assert.equal(p.status, 204);
  assert.equal(p.headers.get('access-control-allow-origin'), '*');
  assert.match(p.headers.get('access-control-allow-methods'), /PATCH/);
  assert.equal(p.headers.get('access-control-allow-headers'), 'content-type,x-foo');
  assert.equal((await s.get('/nope')).headers.get('access-control-allow-origin'), '*');
});

test('R11 HEAD supported', async () => {
  const r = await s.req('HEAD', '/posts/1');
  assert.equal(r.status, 200);
  assert.equal(r.text, '');
});

test('R20 malformed percent encoding -> 400', async () => {
  assert.equal((await s.get('/posts/%E0%A4%A')).status, 400);
});

test('R3 $schema key preserved on write; unknown prototype names 404', async () => {
  await s.req('POST', '/posts', { id: 'p' });
  assert.equal(s.disk().$schema, README_DB.$schema);
  assert.equal((await s.get('/__proto__')).status, 404);
  assert.equal((await s.get('/constructor')).status, 404);
});

test('R3 concurrent mutations all persisted without corruption', async () => {
  await Promise.all(Array.from({ length: 40 }, (_, i) => s.req('POST', '/posts', { id: 'c' + i })));
  assert.equal(s.disk().posts.length, 42);
  const fs = require('node:fs');
  assert.deepEqual(fs.readdirSync(s.dir).filter((f) => f.endsWith('.tmp')), []);
});
