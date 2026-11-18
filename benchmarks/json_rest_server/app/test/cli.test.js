'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { start, tmpDir, ROOT } = require('./helper');

const run = (args, opts = {}) => spawnSync(path.join(ROOT, 'serve'), args, { encoding: 'utf8', timeout: 10000, ...opts });

test('R1 missing db file exits 1', () => {
  const r = run(['/nonexistent/db.json']);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /Cannot load database/);
});

test('R1 invalid db content, no args, bad options', () => {
  const dir = tmpDir();
  fs.writeFileSync(path.join(dir, 'bad.json'), '{ nope');
  assert.equal(run([path.join(dir, 'bad.json')]).status, 1);
  fs.writeFileSync(path.join(dir, 'arr.json'), '[1]');
  assert.equal(run([path.join(dir, 'arr.json')]).status, 1);
  assert.equal(run([]).status, 1);
  assert.equal(run([path.join(dir, 'arr.json'), '--bogus']).status, 1);
  assert.equal(run([path.join(dir, 'arr.json'), '--port', 'abc']).status, 1);
});

test('R1 --help', () => {
  const r = run(['--help']);
  assert.equal(r.status, 0);
  assert.match(r.stdout, /Usage: serve/);
});

test('R1 --port/--host honored and banner printed', async () => {
  // find a free port
  const port = await new Promise((res) => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
  const dir = tmpDir();
  const f = path.join(dir, 'db.json');
  fs.writeFileSync(f, '{"a":[{"id":"1"}]}');
  const { spawn } = require('node:child_process');
  const child = spawn(path.join(ROOT, 'serve'), [f, `--port=${port}`, '--host', '127.0.0.1']);
  let out = '';
  await new Promise((r) => child.stdout.on('data', (d) => { out += d; if (out.includes('http://')) r(); }));
  try {
    assert.equal(out, `JSON Server started on PORT :${port}\nhttp://127.0.0.1:${port}\n`);
    const res = await fetch(`http://127.0.0.1:${port}/a/1`);
    assert.deepEqual(await res.json(), { id: '1' });
  } finally { child.kill('SIGTERM'); }
});

test('R1 default port is 3000 when --port omitted (parseArgs)', () => {
  const { parseArgs } = require('../src/cli');
  assert.deepEqual(parseArgs(['db.json']), { file: 'db.json', port: 3000, host: '127.0.0.1', static: [], help: false });
  assert.deepEqual(parseArgs(['db.json', '-s', 'a', '--static=b', '-p', '8', '-H', 'h']).static, ['a', 'b']);
});

test('R16 malformed request does not crash server', async () => {
  const s = await start();
  try {
    assert.equal((await s.req('POST', '/posts', '')).status, 400);
    assert.equal((await s.get('/posts/%E0%A4%A')).status, 404);
    assert.equal((await s.get('/posts')).status, 200);
  } finally { await s.stop(); }
});
