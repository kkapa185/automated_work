'use strict';
const crypto = require('node:crypto');

const OPS = new Set(['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'in', 'contains', 'startsWith', 'endsWith']);

function getPath(obj, p) {
  let cur = obj;
  for (const k of p) {
    if (cur === null || typeof cur !== 'object' || !Object.hasOwn(cur, k)) return undefined;
    cur = cur[k];
  }
  return cur;
}

// Convert the query value q to the JSON type of field value f when q is a string.
function coerce(q, f) {
  if (typeof q === 'string') {
    if (typeof f === 'number') {
      return q.trim() !== '' && Number.isFinite(Number(q)) ? Number(q) : undefined;
    }
    if (typeof f === 'boolean') return q === 'true' ? true : q === 'false' ? false : undefined;
    if (f === null) return q === 'null' ? null : undefined;
    return q;
  }
  if (typeof f === 'string' && (typeof q === 'number' || typeof q === 'boolean')) return String(q);
  return q;
}

function same(a, b) {
  if (a === b) return true;
  if (a && b && typeof a === 'object' && typeof b === 'object') return JSON.stringify(a) === JSON.stringify(b);
  return false;
}

function test(f, op, q) {
  if (f === undefined) return op === 'ne';
  if (op === 'in') {
    const list = Array.isArray(q) ? q : String(q).split(',');
    return list.some((x) => same(coerce(x, f), f));
  }
  if (op === 'contains' || op === 'startsWith' || op === 'endsWith') {
    if (f === null || typeof f === 'object') return false;
    const s = String(f).toLowerCase();
    const t = String(q).toLowerCase();
    return op === 'contains' ? s.includes(t) : op === 'startsWith' ? s.startsWith(t) : s.endsWith(t);
  }
  const c = coerce(q, f);
  if (op === 'eq') return same(c, f);
  if (op === 'ne') return !same(c, f);
  if (c === undefined || typeof c !== typeof f || (typeof f !== 'number' && typeof f !== 'string')) return false;
  if (op === 'lt') return f < c;
  if (op === 'lte') return f <= c;
  if (op === 'gt') return f > c;
  if (op === 'gte') return f >= c;
  return false;
}

// Flat query-string conditions -> predicate list
function conditionsFromParams(params) {
  const conds = [];
  for (const [key, value] of params) {
    if (key.startsWith('_')) continue;
    const idx = key.lastIndexOf(':');
    let field = key, op = 'eq';
    if (idx >= 0) {
      field = key.slice(0, idx);
      op = key.slice(idx + 1);
      if (!OPS.has(op)) continue; // unknown operator: ignored
    }
    if (!field) continue;
    conds.push({ path: field.split('.'), op, value });
  }
  return (item) => conds.every((c) => test(getPath(item, c.path), c.op, c.value));
}

// _where: returns predicate or null when invalid
function whereToPredicate(node, prefix = []) {
  if (node === null || typeof node !== 'object' || Array.isArray(node)) return null;
  const preds = [];
  for (const [k, v] of Object.entries(node)) {
    if (k === 'and' || k === 'or') {
      if (!Array.isArray(v)) return null;
      const subs = v.map((x) => whereToPredicate(x, prefix));
      if (subs.some((s) => !s)) return null;
      preds.push(k === 'and' ? (it) => subs.every((s) => s(it)) : (it) => subs.some((s) => s(it)));
    } else if (k === 'not') {
      const sub = whereToPredicate(v, prefix);
      if (!sub) return null;
      preds.push((it) => !sub(it));
    } else if (OPS.has(k) && prefix.length) {
      preds.push((it) => test(getPath(it, prefix), k, v));
    } else if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      const sub = whereToPredicate(v, [...prefix, k]);
      if (!sub) return null;
      preds.push(sub);
    } else {
      preds.push((it) => test(getPath(it, [...prefix, k]), 'eq', v));
    }
  }
  return (it) => preds.every((p) => p(it));
}

function buildFilter(params) {
  const w = params.get('_where');
  if (w !== null) {
    try {
      const pred = whereToPredicate(JSON.parse(w));
      if (pred) return pred;
    } catch { /* invalid _where: fall back to normal params */ }
  }
  return conditionsFromParams(params);
}

function rank(v) {
  return typeof v === 'number' ? 0 : typeof v === 'string' ? 1 : typeof v === 'boolean' ? 2 : 3;
}

function cmpValues(a, b) {
  const ra = rank(a), rb = rank(b);
  if (ra !== rb) return ra - rb;
  if (ra === 3) return 0;
  return a < b ? -1 : a > b ? 1 : 0;
}

function sortItems(items, spec) {
  const keys = spec.split(',').map((s) => s.trim()).filter(Boolean).map((s) =>
    s[0] === '-' ? { path: s.slice(1).split('.'), dir: -1 } : { path: (s[0] === '+' ? s.slice(1) : s).split('.'), dir: 1 });
  if (!keys.length) return items;
  const decorated = items.map((it, i) => ({ it, i, vals: keys.map((k) => getPath(it, k.path)) }));
  decorated.sort((x, y) => {
    for (let k = 0; k < keys.length; k++) {
      const a = x.vals[k], b = y.vals[k];
      const am = a === undefined || a === null, bm = b === undefined || b === null;
      if (am || bm) { if (am && bm) continue; return am ? 1 : -1; } // missing last
      const c = cmpValues(a, b);
      if (c) return c * keys[k].dir;
    }
    return x.i - y.i;
  });
  return decorated.map((d) => d.it);
}

function positiveInt(s, def) {
  if (s === null || !/^\s*\d+\s*$/.test(s)) return def;
  const n = parseInt(s, 10);
  return n >= 1 ? n : def;
}

function paginate(items, params) {
  const perPage = positiveInt(params.get('_per_page'), 10);
  const total = items.length;
  const pages = Math.max(1, Math.ceil(total / perPage));
  const page = Math.min(positiveInt(params.get('_page'), 1), pages);
  const start = (page - 1) * perPage;
  return {
    first: 1,
    prev: page > 1 ? page - 1 : null,
    next: page < pages ? page + 1 : null,
    last: pages,
    pages,
    items: total,
    data: items.slice(start, start + perPage),
  };
}

function singular(name) {
  if (name.endsWith('ies') && name.length > 3) return name.slice(0, -3) + 'y';
  if (name.endsWith('s') && name.length > 1) return name.slice(0, -1);
  return name;
}

function pluralCandidates(name) {
  const c = [name + 's', name + 'es'];
  if (name.endsWith('y')) c.unshift(name.slice(0, -1) + 'ies');
  return c;
}

// Returns function(item) -> item with embedded relations
function makeEmbedder(data, collection, embeds) {
  const fk = singular(collection) + 'Id';
  const steps = [];
  for (const e of embeds) {
    if (Array.isArray(data[e]) && Object.hasOwn(data, e)) {
      const byParent = new Map();
      for (const child of data[e]) {
        if (child && typeof child === 'object' && child[fk] !== undefined && child[fk] !== null) {
          const k = String(child[fk]);
          if (!byParent.has(k)) byParent.set(k, []);
          byParent.get(k).push(child);
        }
      }
      steps.push((item, out) => { out[e] = item.id === undefined ? [] : byParent.get(String(item.id)) || []; });
      continue;
    }
    const pname = pluralCandidates(e).find((p) => Object.hasOwn(data, p) && Array.isArray(data[p]));
    if (pname) {
      const byId = new Map();
      for (const p of data[pname]) if (p && p.id !== undefined) byId.set(String(p.id), p);
      steps.push((item, out) => {
        const ref = item[e + 'Id'];
        out[e] = ref === undefined || ref === null ? null : byId.get(String(ref)) || null;
      });
    }
  }
  if (!steps.length) return (it) => it;
  return (item) => {
    const out = { ...item };
    for (const s of steps) s(item, out);
    return out;
  };
}

function genId(existing) {
  for (;;) {
    const id = crypto.randomBytes(4).toString('hex');
    if (!existing.has(id)) return id;
  }
}

module.exports = { buildFilter, sortItems, paginate, makeEmbedder, singular, genId, getPath, OPS };
