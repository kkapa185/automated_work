'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const json5 = require('./json5');

function isObj(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }

function parseDb(text, file) {
  let data;
  if (path.extname(file).toLowerCase() === '.json5') data = json5.parse(text);
  else {
    try { data = JSON.parse(text); } catch { data = json5.parse(text); }
  }
  if (!isObj(data)) throw new Error('Database root must be a JSON object');
  return data;
}

class Store {
  constructor(file) {
    this.file = path.resolve(file);
    this.data = parseDb(fs.readFileSync(this.file, 'utf8'), this.file);
    this.seq = 0;
    this.inflight = null;
    this.queued = null;
  }

  has(name) { return name !== '$schema' && Object.hasOwn(this.data, name); }
  kind(name) {
    if (!this.has(name)) return null;
    const v = this.data[name];
    if (Array.isArray(v)) return 'array';
    if (isObj(v)) return 'object';
    return null;
  }
  collections() { return Object.keys(this.data).filter((k) => this.kind(k) === 'array'); }

  newId(coll) {
    const used = new Set(this.data[coll].map((x) => (isObj(x) ? String(x.id) : '')));
    for (;;) {
      const id = crypto.randomBytes(4).toString('hex');
      if (!used.has(id)) return id;
    }
  }

  // Persist current state atomically. Concurrent callers are coalesced; the returned promise
  // resolves once a write that started after the call has completed.
  save() {
    if (!this.inflight) {
      this.inflight = this._write().finally(() => { this.inflight = null; });
      return this.inflight;
    }
    if (!this.queued) {
      this.queued = this.inflight.catch(() => {}).then(() => {
        this.queued = null;
        this.inflight = this._write().finally(() => { this.inflight = null; });
        return this.inflight;
      });
    }
    return this.queued;
  }

  async _write() {
    const tmp = `${this.file}.${process.pid}.${++this.seq}.tmp`;
    const text = JSON.stringify(this.data, null, 2) + '\n';
    try {
      await fs.promises.writeFile(tmp, text);
      await fs.promises.rename(tmp, this.file);
    } catch (e) {
      await fs.promises.rm(tmp, { force: true });
      throw e;
    }
  }
}

module.exports = { Store, isObj };
