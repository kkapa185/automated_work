'use strict';
const fs = require('node:fs');
const path = require('node:path');
const json5 = require('./json5');

function load(file) {
  const text = fs.readFileSync(file, 'utf8');
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    data = json5.parse(text);
  }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Database top level must be an object');
  }
  return data;
}

class Store {
  constructor(file) {
    this.file = path.resolve(file);
    this.data = load(this.file);
    this.chain = Promise.resolve();
    this.counter = 0;
  }

  // Serialize snapshot now, write later (in order), atomically.
  save() {
    const snapshot = JSON.stringify(this.data, null, 2) + '\n';
    const run = async () => {
      const tmp = path.join(path.dirname(this.file), `.${path.basename(this.file)}.${process.pid}.${++this.counter}.tmp`);
      try {
        await fs.promises.writeFile(tmp, snapshot);
        await fs.promises.rename(tmp, this.file);
      } catch (e) {
        await fs.promises.rm(tmp, { force: true }).catch(() => {});
        throw e;
      }
    };
    const p = this.chain.then(run);
    this.chain = p.catch(() => {});
    return p;
  }
}

module.exports = { Store, load };
