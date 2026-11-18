'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { isObj } = require('./store');
const { listQuery, embedItems, singular, sameId } = require('./query');

const MIME = {
  '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.txt': 'text/plain; charset=utf-8', '.xml': 'application/xml',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
  '.webp': 'image/webp', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf',
  '.map': 'application/json', '.wasm': 'application/wasm', '.pdf': 'application/pdf', '.md': 'text/markdown; charset=utf-8',
};
const MAX_BODY = 50 * 1024 * 1024;

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
}

function sendJson(req, res, status, body) {
  const text = JSON.stringify(body, null, 2);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(text),
  });
  res.end(req.method === 'HEAD' ? undefined : text);
}

const notFound = (req, res) => sendJson(req, res, 404, { error: 'Not Found' });

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) { reject(new HttpError(413, 'Payload Too Large')); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function parseObjectBody(text) {
  let v;
  try { v = JSON.parse(text); } catch { throw new HttpError(400, 'Invalid JSON body'); }
  if (!isObj(v)) throw new HttpError(400, 'Body must be a JSON object');
  return v;
}

function findIndex(arr, id) { return arr.findIndex((x) => isObj(x) && sameId(x.id, id)); }

function serveStatic(dirs, req, res, pathname) {
  let rel;
  try { rel = decodeURIComponent(pathname); } catch { return false; }
  if (rel.includes('\0')) return false;
  for (const dir of dirs) {
    const root = path.resolve(dir);
    let file = path.resolve(root, '.' + path.sep + rel);
    if (file !== root && !file.startsWith(root + path.sep)) continue;
    let st;
    try { st = fs.statSync(file); } catch { continue; }
    if (st.isDirectory()) {
      file = path.join(file, 'index.html');
      try { st = fs.statSync(file); } catch { continue; }
    }
    if (!st.isFile()) continue;
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'Content-Length': st.size,
    });
    if (req.method === 'HEAD') res.end(); else fs.createReadStream(file).pipe(res);
    return true;
  }
  return false;
}

function createServer(store, { staticDirs = [] } = {}) {
  async function handle(req, res) {
    cors(res);
    const url = new URL(req.url, 'http://localhost');
    const method = req.method;
    if (method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Methods': 'GET,HEAD,PUT,PATCH,POST,DELETE,OPTIONS',
        'Access-Control-Allow-Headers': req.headers['access-control-request-headers'] || '*',
        'Content-Length': 0,
      });
      return res.end();
    }
    let segs;
    try { segs = url.pathname.split('/').filter(Boolean).map(decodeURIComponent); } catch { return notFound(req, res); }
    const name = segs[0];
    const kind = segs.length ? store.kind(name) : null;
    if (!kind || segs.length > 2) {
      if ((method === 'GET' || method === 'HEAD') && serveStatic(staticDirs, req, res, url.pathname)) return;
      return notFound(req, res);
    }
    const params = url.searchParams;

    if (kind === 'object') {
      if (segs.length !== 1) return notFound(req, res);
      if (method === 'GET' || method === 'HEAD') return sendJson(req, res, 200, store.data[name]);
      if (method === 'PUT' || method === 'PATCH') {
        const body = parseObjectBody(await readBody(req));
        store.data[name] = method === 'PUT' ? body : { ...store.data[name], ...body };
        await store.save();
        return sendJson(req, res, 200, store.data[name]);
      }
      return notFound(req, res);
    }

    const arr = store.data[name];
    const embeds = () => params.getAll('_embed').flatMap((s) => s.split(',')).map((s) => s.trim()).filter(Boolean);

    if (segs.length === 1) {
      if (method === 'GET' || method === 'HEAD') return sendJson(req, res, 200, listQuery(store, name, params));
      if (method === 'POST') {
        const body = parseObjectBody(await readBody(req));
        delete body.id;
        const item = { id: store.newId(name), ...body };
        arr.push(item);
        await store.save();
        return sendJson(req, res, 201, item);
      }
      return notFound(req, res);
    }

    const id = segs[1];
    const idx = findIndex(arr, id);
    if (method === 'PUT' || method === 'PATCH') {
      // consume the body even for unknown ids
      const raw = await readBody(req);
      if (idx < 0) return notFound(req, res);
      const body = parseObjectBody(raw);
      delete body.id;
      const cur = arr[idx];
      arr[idx] = method === 'PUT' ? { id: cur.id, ...body } : { ...cur, ...body, id: cur.id };
      await store.save();
      return sendJson(req, res, 200, arr[idx]);
    }
    if (idx < 0) return notFound(req, res);
    if (method === 'GET' || method === 'HEAD') {
      return sendJson(req, res, 200, embedItems(store, name, [arr[idx]], embeds())[0]);
    }
    if (method === 'DELETE') {
      const [removed] = arr.splice(idx, 1);
      const fk = `${singular(name)}Id`;
      const dependent = new Set(params.getAll('_dependent').flatMap((s) => s.split(',')).map((s) => s.trim()).filter(Boolean));
      for (const other of store.collections()) {
        if (other === name) continue;
        const list = store.data[other];
        if (dependent.has(other)) {
          store.data[other] = list.filter((x) => !(isObj(x) && sameId(x[fk], removed.id)));
        } else {
          for (const x of list) if (isObj(x) && Object.hasOwn(x, fk) && sameId(x[fk], removed.id)) x[fk] = null;
        }
      }
      await store.save();
      return sendJson(req, res, 200, removed);
    }
    return notFound(req, res);
  }

  return http.createServer((req, res) => {
    handle(req, res).catch((err) => {
      if (res.headersSent) { res.destroy(); return; }
      const status = err instanceof HttpError ? err.status : 500;
      sendJson(req, res, status, { error: status === 500 ? 'Internal Server Error' : err.message });
    });
  });
}

module.exports = { createServer };
