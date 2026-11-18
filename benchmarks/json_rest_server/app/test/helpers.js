'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createApp } = require('../src/app');

const README_DB = {
  $schema: './node_modules/json-server/schema.json',
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

async function start(db = README_DB, { name = 'db.json', raw, staticFiles } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'jrs-'));
  const file = path.join(dir, name);
  fs.writeFileSync(file, raw !== undefined ? raw : JSON.stringify(db, null, 2));
  const staticDirs = [];
  if (staticFiles) {
    const sd = path.join(dir, 'static');
    fs.mkdirSync(sd);
    for (const [f, c] of Object.entries(staticFiles)) {
      fs.mkdirSync(path.dirname(path.join(sd, f)), { recursive: true });
      fs.writeFileSync(path.join(sd, f), c);
    }
    staticDirs.push(sd);
  }
  const app = createApp({ dbPath: file, staticDirs });
  await new Promise((r) => app.server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${app.server.address().port}`;
  async function req(method, url, body, headers = {}) {
    const init = { method, headers: { ...headers } };
    if (body !== undefined) {
      init.body = typeof body === 'string' ? body : JSON.stringify(body);
      init.headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(base + url, init);
    const text = await res.text();
    let json;
    try { json = JSON.parse(text); } catch { json = undefined; }
    return { status: res.status, headers: res.headers, text, json };
  }
  return {
    base, dir, file, req, app,
    get: (u) => req('GET', u),
    disk: () => JSON.parse(fs.readFileSync(file, 'utf8')),
    close: () => new Promise((r) => { app.server.closeAllConnections(); app.server.close(r); }),
  };
}

module.exports = { start, README_DB };
