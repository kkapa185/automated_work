'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { Store } = require('./db');
const q = require('./query');

const MIME = {
  '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8', '.xml': 'application/xml', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
  '.webp': 'image/webp', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2',
  '.ttf': 'font/ttf', '.map': 'application/json', '.wasm': 'application/wasm', '.pdf': 'application/pdf',
};

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

function createApp({ dbPath, staticDirs = [] }) {
  const store = new Store(dbPath);
  const dirs = staticDirs.map((d) => path.resolve(d));

  const isCollection = (name) => Object.hasOwn(store.data, name) && Array.isArray(store.data[name]);
  const isObject = (name) => Object.hasOwn(store.data, name) && store.data[name] !== null
    && typeof store.data[name] === 'object' && !Array.isArray(store.data[name]);
  const isResource = (name) => isCollection(name) || isObject(name);

  function send(res, status, body, req) {
    const text = JSON.stringify(body, null, 2);
    res.writeHead(status, {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Length': Buffer.byteLength(text),
    });
    res.end(req && req.method === 'HEAD' ? undefined : text);
  }
  const notFound = (res, req) => send(res, 404, { error: 'NotFound' }, req);

  function readBody(req) {
    return new Promise((resolve, reject) => {
      const chunks = [];
      let size = 0;
      req.on('data', (c) => {
        size += c.length;
        if (size > 50 * 1024 * 1024) { reject(new HttpError(413, 'PayloadTooLarge')); req.destroy(); return; }
        chunks.push(c);
      });
      req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
      req.on('error', reject);
    });
  }

  async function readJsonObject(req) {
    const text = await readBody(req);
    let body;
    try { body = JSON.parse(text); } catch { throw new HttpError(400, 'Invalid JSON body'); }
    if (body === null || typeof body !== 'object' || Array.isArray(body)) {
      throw new HttpError(400, 'Body must be a JSON object');
    }
    return body;
  }

  function embedList(params) {
    return params.getAll('_embed').flatMap((s) => s.split(',')).map((s) => s.trim()).filter(Boolean);
  }

  function list(name, params) {
    let items = store.data[name];
    const filter = q.buildFilter(params);
    items = items.filter((it) => it !== null && typeof it === 'object' && filter(it));
    const sort = params.get('_sort');
    if (sort) items = q.sortItems(items, sort);
    const embed = q.makeEmbedder(store.data, name, embedList(params));
    if (params.has('_page') || params.has('_per_page')) {
      const page = q.paginate(items, params);
      page.data = page.data.map(embed);
      return page;
    }
    return items.map(embed);
  }

  const findIndex = (name, id) => store.data[name].findIndex((it) => it && it.id !== undefined && String(it.id) === id);

  async function handleApi(req, res, segs, params) {
    const [name, id] = segs;
    const m = req.method;
    if (isObject(name)) {
      if (id !== undefined) return notFound(res, req);
      if (m === 'GET' || m === 'HEAD') return send(res, 200, store.data[name], req);
      if (m === 'PUT' || m === 'PATCH') {
        const body = await readJsonObject(req);
        store.data[name] = m === 'PUT' ? body : { ...store.data[name], ...body };
        await store.save();
        return send(res, 200, store.data[name]);
      }
      return notFound(res, req);
    }
    // collection
    const items = store.data[name];
    if (id === undefined) {
      if (m === 'GET' || m === 'HEAD') return send(res, 200, list(name, params), req);
      if (m === 'POST') {
        const body = await readJsonObject(req);
        const ids = new Set(items.filter((x) => x && x.id !== undefined).map((x) => String(x.id)));
        let item;
        if (body.id === undefined || body.id === null || body.id === '') {
          const { id: _drop, ...rest } = body;
          item = { id: q.genId(ids), ...rest };
        } else {
          if (typeof body.id === 'object') throw new HttpError(400, 'Invalid id');
          if (ids.has(String(body.id))) throw new HttpError(400, 'Id already exists');
          item = { ...body, id: String(body.id) };
        }
        items.push(item);
        await store.save();
        return send(res, 201, item);
      }
      return notFound(res, req);
    }
    const idx = findIndex(name, id);
    if (idx < 0) return notFound(res, req);
    const cur = items[idx];
    if (m === 'GET' || m === 'HEAD') {
      return send(res, 200, q.makeEmbedder(store.data, name, embedList(params))(cur), req);
    }
    if (m === 'PUT' || m === 'PATCH') {
      const body = await readJsonObject(req);
      const next = m === 'PUT' ? { id: cur.id, ...body } : { ...cur, ...body };
      next.id = cur.id;
      items[idx] = next;
      await store.save();
      return send(res, 200, next);
    }
    if (m === 'DELETE') {
      items.splice(idx, 1);
      const fk = q.singular(name) + 'Id';
      for (const dep of params.getAll('_dependent').flatMap((s) => s.split(',')).map((s) => s.trim()).filter(Boolean)) {
        if (dep !== name && isCollection(dep)) {
          store.data[dep] = store.data[dep].filter((c) => !(c && c[fk] !== undefined && c[fk] !== null && String(c[fk]) === id));
        }
      }
      await store.save();
      return send(res, 200, cur);
    }
    return notFound(res, req);
  }

  function serveStatic(req, res, pathname) {
    if (req.method !== 'GET' && req.method !== 'HEAD') return false;
    let rel;
    try { rel = decodeURIComponent(pathname); } catch { return false; }
    if (rel.includes('\0')) return false;
    for (const dir of dirs) {
      let file = path.resolve(dir, '.' + path.posix.normalize('/' + rel));
      if (file !== dir && !file.startsWith(dir + path.sep)) continue;
      try {
        let st = fs.statSync(file);
        if (st.isDirectory()) { file = path.join(file, 'index.html'); st = fs.statSync(file); }
        if (!st.isFile()) continue;
        res.writeHead(200, {
          'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream',
          'Content-Length': st.size,
        });
        if (req.method === 'HEAD') res.end(); else fs.createReadStream(file).pipe(res);
        return true;
      } catch { /* try next dir */ }
    }
    return false;
  }

  async function handle(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Methods': 'GET,HEAD,PUT,PATCH,POST,DELETE',
        'Access-Control-Allow-Headers': req.headers['access-control-request-headers'] || '*',
        'Content-Length': 0,
      });
      return res.end();
    }
    const url = new URL(req.url, 'http://localhost');
    let segs;
    try {
      segs = url.pathname.split('/').filter(Boolean).map(decodeURIComponent);
    } catch { throw new HttpError(400, 'Malformed URL'); }
    if (segs.length && segs.length <= 2 && isResource(segs[0])) {
      return handleApi(req, res, segs, url.searchParams);
    }
    if (serveStatic(req, res, url.pathname)) return;
    return notFound(res, req);
  }

  const server = http.createServer((req, res) => {
    handle(req, res).catch((e) => {
      if (res.headersSent) { res.end(); return; }
      if (e instanceof HttpError) return send(res, e.status, { error: e.message });
      console.error(e);
      send(res, 500, { error: 'InternalServerError' });
    });
  });

  return { server, store };
}

module.exports = { createApp };
