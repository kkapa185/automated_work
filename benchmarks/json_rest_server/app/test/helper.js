'use strict';
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

const README_DB = {
  posts: [
    { id: '1', title: 'a title', views: 100 },
    { id: '2', title: 'another title', views: 200 },
  ],
  comments: [
    { id: '1', text: 'a comment about post 1', postId: '1' },
    { id: '2', text: 'another comment about post 1', postId: '1' },
  ],
  profile: { name: 'typicode' },
};

function tmpDir() { return fs.mkdtempSync(path.join(os.tmpdir(), 'jrs-')); }

// Start ./serve on an ephemeral port; db is an object (written as JSON) or {file, text}.
async function start(db = README_DB, { args = [], file = 'db.json', text, cwd, dir } = {}) {
  dir = dir || tmpDir();
  const dbFile = path.join(dir, file);
  if (db !== null) fs.writeFileSync(dbFile, text !== undefined ? text : JSON.stringify(db, null, 2));
  const child = spawn(path.join(ROOT, 'serve'), [dbFile, '--port', '0', ...args], { cwd: cwd || dir });
  let out = '', err = '';
  child.stderr.on('data', (d) => { err += d; });
  const port = await new Promise((resolve, reject) => {
    child.stdout.on('data', (d) => {
      out += d;
      const m = /http:\/\/[^:]+:(\d+)/.exec(out);
      if (m) resolve(+m[1]);
    });
    child.on('exit', (c) => reject(new Error(`server exited ${c}: ${err}`)));
  });
  const base = `http://127.0.0.1:${port}`;
  const srv = {
    base, dir, dbFile, child, out: () => out,
    stop: () => new Promise((r) => {
      if (child.exitCode !== null || child.signalCode !== null) return r();
      child.removeAllListeners('exit'); child.on('exit', r); child.kill('SIGTERM');
    }),
    disk: () => JSON.parse(fs.readFileSync(dbFile, 'utf8')),
    async req(method, p, body, headers = {}) {
      const init = { method, headers: { ...headers } };
      if (body !== undefined) {
        init.body = typeof body === 'string' ? body : JSON.stringify(body);
        init.headers['Content-Type'] = 'application/json';
      }
      const res = await fetch(base + p, init);
      const raw = await res.text();
      let json; try { json = JSON.parse(raw); } catch { json = undefined; }
      return { status: res.status, headers: res.headers, raw, json };
    },
    get: (p) => srv.req('GET', p),
  };
  return srv;
}

module.exports = { start, README_DB, tmpDir, ROOT };
