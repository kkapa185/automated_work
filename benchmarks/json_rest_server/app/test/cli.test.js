'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { start, README_DB } = require('./helpers');

const SERVE = path.join(__dirname, '..', 'serve');

function launch(args, cwd) {
  const p = spawn(SERVE, args, { cwd: cwd || os.tmpdir() });
  let out = '';
  const ready = new Promise((resolve, reject) => {
    p.stdout.on('data', (d) => { out += d; if (out.includes('http://')) resolve(); });
    p.on('exit', (c) => reject(new Error('exited ' + c)));
    setTimeout(() => reject(new Error('timeout')), 5000);
  });
  return { p, ready, out: () => out, stop: () => new Promise((r) => { p.on('exit', r); p.kill('SIGTERM'); }) };
}
const freePort = () => new Promise((r) => {
  const s = require('node:net').createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); });
});
const tmpdb = (name, content) => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'jrs-cli-'));
  const f = path.join(d, name);
  fs.writeFileSync(f, content);
  return f;
};

test('R1/R3 start, mutate, restart: data persisted and re-read', async () => {
  const f = tmpdb('db.json', JSON.stringify(README_DB));
  const port = await freePort();
  let srv = launch([f, '--port', String(port)]);
  await srv.ready;
  assert.match(srv.out(), new RegExp(`JSON Server started on PORT :${port}`));
  let r = await fetch(`http://127.0.0.1:${port}/posts/1`);
  assert.equal(await r.text(), '{\n  "id": "1",\n  "title": "a title",\n  "views": 100\n}');
  r = await fetch(`http://127.0.0.1:${port}/posts`, { method: 'POST', body: JSON.stringify({ id: 'n', title: 'new' }) });
  assert.equal(r.status, 201);
  await fetch(`http://127.0.0.1:${port}/posts/1`, { method: 'DELETE' });
  await srv.stop();
  const onDisk = JSON.parse(fs.readFileSync(f, 'utf8'));
  assert.deepEqual(onDisk.posts.map((p) => p.id), ['2', 'n']);
  srv = launch([f, '-p', String(port)]);
  await srv.ready;
  r = await fetch(`http://127.0.0.1:${port}/posts`);
  assert.deepEqual((await r.json()).map((p) => p.id), ['2', 'n']);
  await srv.stop();
});

test('R2 JSON5 file served, written back as valid data', async () => {
  const f = tmpdb('db.json5', "{ posts: [ {id:'1', t:'x',}, ], // c\n profile: {a:1} }");
  const port = await freePort();
  const srv = launch([f, '--port=' + port, '--host', '127.0.0.1']);
  await srv.ready;
  const base = `http://127.0.0.1:${port}`;
  assert.deepEqual(await (await fetch(base + '/posts/1')).json(), { id: '1', t: 'x' });
  await fetch(base + '/profile', { method: 'PATCH', body: '{"b":2}' });
  await srv.stop();
  assert.deepEqual(JSON.parse(fs.readFileSync(f, 'utf8')).profile, { a: 1, b: 2 });
});

test('R1 errors: missing file, bad json, bad args, --help', () => {
  let r = spawnSync(SERVE, ['/nonexistent.json']);
  assert.notEqual(r.status, 0);
  r = spawnSync(SERVE, [tmpdb('bad.json', '{oops')]);
  assert.notEqual(r.status, 0);
  r = spawnSync(SERVE, [tmpdb('arr.json', '[1]')]);
  assert.notEqual(r.status, 0);
  r = spawnSync(SERVE, []);
  assert.notEqual(r.status, 0);
  r = spawnSync(SERVE, [tmpdb('d.json', '{}'), '--port', 'abc']);
  assert.notEqual(r.status, 0);
  r = spawnSync(SERVE, ['--help']);
  assert.equal(r.status, 0);
  assert.match(r.stdout.toString(), /--static/);
});

test('R19 --static (repeatable) and default ./public', async () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'jrs-st-'));
  fs.mkdirSync(path.join(d, 'public'));
  fs.writeFileSync(path.join(d, 'public', 'index.html'), '<h1>hi</h1>');
  fs.mkdirSync(path.join(d, 'extra'));
  fs.writeFileSync(path.join(d, 'extra', 'a.css'), 'body{}');
  fs.writeFileSync(path.join(d, 'db.json'), '{"posts":[]}');
  const port = await freePort();
  const srv = launch(['db.json', '-p', String(port), '-s', 'extra'], d);
  await srv.ready;
  const base = `http://127.0.0.1:${port}`;
  let r = await fetch(base + '/');
  assert.equal(await r.text(), '<h1>hi</h1>');
  assert.match(r.headers.get('content-type'), /text\/html/);
  r = await fetch(base + '/a.css');
  assert.match(r.headers.get('content-type'), /text\/css/);
  assert.equal(r.status, 200);
  await srv.stop();
});

test('R19 static module: mime, traversal blocked, API precedence, 404', async () => {
  const s = await start({ posts: [{ id: '1' }] }, { staticFiles: { 'index.html': 'IDX', 'app.js': '1', 'posts': 'shadow', 'sub/x.json': '{}', 'img.png': 'x' } });
  try {
    assert.equal((await s.get('/')).text, 'IDX');
    assert.match((await s.get('/app.js')).headers.get('content-type'), /javascript/);
    assert.match((await s.get('/img.png')).headers.get('content-type'), /image\/png/);
    assert.equal((await s.get('/sub/x.json')).status, 200);
    assert.deepEqual((await s.get('/posts')).json, [{ id: '1' }]);
    assert.equal((await s.get('/nofile.txt')).json.error, 'NotFound');
    const raw = await new Promise((resolve) => {
      const sock = require('node:net').connect(new URL(s.base).port, '127.0.0.1', () => sock.write('GET /../../../../etc/passwd HTTP/1.0\r\n\r\n'));
      let b = ''; sock.on('data', (d) => (b += d)); sock.on('end', () => resolve(b));
    });
    assert.match(raw, /404/);
    assert.equal((await s.get('/%2e%2e/%2e%2e/etc/passwd')).status, 404);
  } finally { await s.close(); }
});
