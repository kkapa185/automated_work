'use strict';
const { isObj } = require('./store');

const OPS = new Set(['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'in', 'contains', 'startsWith', 'endsWith']);

function getPath(obj, p) {
  let cur = obj;
  for (const part of p.split('.')) {
    if (cur === null || typeof cur !== 'object' || !Object.hasOwn(cur, part)) return undefined;
    cur = cur[part];
  }
  return cur;
}

function numeric(x) {
  if (typeof x === 'number') return x;
  if (typeof x === 'string' && x.trim() !== '') return Number(x);
  return NaN;
}

function eq(v, operand) {
  if (v === undefined) return false;
  if (v === null) return operand === null || operand === 'null';
  if (typeof v === 'number') return v === numeric(operand);
  if (typeof v === 'boolean') return String(v) === String(operand);
  if (typeof v === 'string') return v === String(operand);
  return false;
}

function order(v, operand) {
  // returns negative/zero/positive, or NaN when incomparable
  if (typeof v === 'number') {
    const o = numeric(operand);
    return Number.isNaN(o) || Number.isNaN(v) ? NaN : v - o;
  }
  if (typeof v === 'string') {
    if (typeof operand === 'number') {
      const nv = numeric(v);
      return Number.isNaN(nv) ? NaN : nv - operand;
    }
    if (typeof operand !== 'string') return NaN;
    return v < operand ? -1 : v > operand ? 1 : 0;
  }
  return NaN;
}

function test(v, op, operand) {
  switch (op) {
    case 'eq': return eq(v, operand);
    case 'ne': return !eq(v, operand);
    case 'lt': return order(v, operand) < 0;
    case 'lte': return order(v, operand) <= 0;
    case 'gt': return order(v, operand) > 0;
    case 'gte': return order(v, operand) >= 0;
    case 'in': return Array.isArray(operand) && operand.some((o) => eq(v, o));
    case 'contains': case 'startsWith': case 'endsWith': {
      if (typeof v !== 'string' || operand === null || typeof operand === 'object') return false;
      const a = v.toLowerCase(), b = String(operand).toLowerCase();
      return op === 'contains' ? a.includes(b) : op === 'startsWith' ? a.startsWith(b) : a.endsWith(b);
    }
    default: return false;
  }
}

// Build predicate from URL search params (conditions only).
function conditionsFromParams(params) {
  const conds = [];
  for (const [k, raw] of params) {
    if (k.startsWith('_')) continue;
    let field = k, op = 'eq';
    const idx = k.lastIndexOf(':');
    if (idx > 0 && OPS.has(k.slice(idx + 1))) { field = k.slice(0, idx); op = k.slice(idx + 1); }
    conds.push({ field, op, operand: op === 'in' ? raw.split(',') : raw });
  }
  return (item) => conds.every((c) => test(getPath(item, c.field), c.op, c.operand));
}

// Build predicate from a parsed _where object; returns null if invalid.
function whereToPredicate(w, prefix = '') {
  if (!isObj(w)) return null;
  const preds = [];
  for (const [k, val] of Object.entries(w)) {
    if (k === 'and' || k === 'or') {
      if (!Array.isArray(val)) return null;
      const subs = val.map((x) => whereToPredicate(x, prefix));
      if (subs.some((s) => !s)) return null;
      preds.push(k === 'and' ? (it) => subs.every((s) => s(it)) : (it) => subs.some((s) => s(it)));
    } else if (k === 'not') {
      const sub = whereToPredicate(val, prefix);
      if (!sub) return null;
      preds.push((it) => !sub(it));
    } else {
      const field = prefix ? `${prefix}.${k}` : k;
      if (isObj(val)) {
        const keys = Object.keys(val);
        const opKeys = keys.filter((x) => OPS.has(x));
        if (keys.length && opKeys.length === keys.length) {
          for (const op of opKeys) {
            const operand = val[op];
            preds.push((it) => test(getPath(it, field), op, operand));
          }
        } else {
          const sub = whereToPredicate(val, field);
          if (!sub) return null;
          preds.push(sub);
        }
      } else {
        preds.push((it) => test(getPath(it, field), 'eq', val));
      }
    }
  }
  return (it) => preds.every((p) => p(it));
}

function compareValues(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (typeof a === 'string' && typeof b === 'string') return a.toLowerCase().localeCompare(b.toLowerCase());
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b);
  const rank = (x) => (typeof x === 'number' ? 0 : typeof x === 'string' ? 1 : 2);
  return rank(a) - rank(b);
}

function sortItems(items, sortParam) {
  const keys = sortParam.split(',').map((s) => s.trim()).filter(Boolean).map((s) =>
    s.startsWith('-') ? { f: s.slice(1), dir: -1 } : { f: s.replace(/^\+/, ''), dir: 1 });
  if (!keys.length) return items;
  return items.map((it, i) => ({ it, i })).sort((x, y) => {
    for (const { f, dir } of keys) {
      const a = getPath(x.it, f), b = getPath(y.it, f);
      const am = a === undefined || a === null, bm = b === undefined || b === null;
      if (am || bm) { if (am && bm) continue; return am ? 1 : -1; }
      const c = compareValues(a, b);
      if (c) return dir * c;
    }
    return x.i - y.i;
  }).map((x) => x.it);
}

function posInt(v, dflt) {
  if (v === null || !/^\s*\d+\s*$/.test(v)) return dflt;
  const n = parseInt(v, 10);
  return n >= 1 ? n : dflt;
}

function paginate(items, params) {
  const perPage = posInt(params.get('_per_page'), 10);
  const total = items.length;
  const pages = Math.max(1, Math.ceil(total / perPage));
  const page = Math.min(posInt(params.get('_page'), 1), pages);
  return {
    first: 1,
    prev: page > 1 ? page - 1 : null,
    next: page < pages ? page + 1 : null,
    last: pages,
    pages,
    items: total,
    data: items.slice((page - 1) * perPage, page * perPage),
  };
}

function singular(name) {
  if (/ies$/.test(name)) return name.slice(0, -3) + 'y';
  if (/s$/.test(name)) return name.slice(0, -1);
  return name;
}

function sameId(a, b) { return a !== undefined && a !== null && b !== undefined && b !== null && String(a) === String(b); }

function embedItems(store, coll, items, embeds) {
  const fk = `${singular(coll)}Id`;
  const specs = embeds.map((name) => {
    if (store.kind(name) === 'array' && name !== coll) return { name, type: 'child' };
    const parent = store.collections().find((c) => singular(c) === name || c === name);
    if (parent) return { name, type: 'parent', coll: parent };
    return null;
  }).filter(Boolean);
  if (!specs.length) return items;
  // index children by foreign key to avoid quadratic work
  const idx = new Map();
  for (const s of specs) {
    if (s.type === 'child') {
      const m = new Map();
      for (const c of store.data[s.name]) {
        if (!isObj(c) || c[fk] === undefined || c[fk] === null) continue;
        const k = String(c[fk]);
        if (!m.has(k)) m.set(k, []);
        m.get(k).push(c);
      }
      idx.set(s.name, m);
    } else {
      const m = new Map();
      for (const p of store.data[s.coll]) if (isObj(p) && p.id !== undefined) m.set(String(p.id), p);
      idx.set(s.name, m);
    }
  }
  return items.map((it) => {
    const out = { ...it };
    for (const s of specs) {
      if (s.type === 'child') out[s.name] = (idx.get(s.name).get(String(it.id)) || []).slice();
      else {
        const v = it[`${s.name}Id`];
        out[s.name] = v === undefined || v === null ? null : (idx.get(s.name).get(String(v)) || null);
      }
    }
    return out;
  });
}

function listQuery(store, coll, params) {
  let items = store.data[coll].filter(isObj);
  let pred = null;
  if (params.has('_where')) {
    let parsed;
    try { parsed = JSON.parse(params.get('_where')); } catch { parsed = undefined; }
    pred = whereToPredicate(parsed);
  }
  if (!pred) pred = conditionsFromParams(params);
  items = items.filter(pred);
  if (params.has('_sort')) items = sortItems(items, params.get('_sort'));
  const embeds = params.getAll('_embed').flatMap((s) => s.split(',')).map((s) => s.trim()).filter(Boolean);
  const paged = params.has('_page') || params.has('_per_page');
  if (paged) {
    const res = paginate(items, params);
    res.data = embedItems(store, coll, res.data, embeds);
    return res;
  }
  return embedItems(store, coll, items, embeds);
}

module.exports = { listQuery, embedItems, singular, sameId, getPath, test, whereToPredicate };
