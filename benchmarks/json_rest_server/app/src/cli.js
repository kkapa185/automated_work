'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { Store } = require('./store');
const { createServer } = require('./server');

const USAGE = `Usage: serve <db.json|db.json5> [options]

Options:
  -p, --port <port>     Port (default 3000)
  -H, --host <host>     Host (default 127.0.0.1)
  -s, --static <dir>    Static files directory (repeatable; ./public is served if it exists)
  -h, --help            Show this help`;

function parseArgs(argv) {
  const o = { file: null, port: 3000, host: '127.0.0.1', static: [], help: false };
  for (let i = 0; i < argv.length; i++) {
    let a = argv[i], inline = null;
    const m = /^(--[a-z-]+)=(.*)$/.exec(a);
    if (m) { a = m[1]; inline = m[2]; }
    const val = () => {
      if (inline !== null) return inline;
      if (i + 1 >= argv.length) throw new Error(`Missing value for ${a}`);
      return argv[++i];
    };
    if (a === '-h' || a === '--help') o.help = true;
    else if (a === '-p' || a === '--port') {
      const v = val();
      if (!/^\d+$/.test(v) || +v > 65535) throw new Error(`Invalid port: ${v}`);
      o.port = +v;
    } else if (a === '-H' || a === '--host') o.host = val();
    else if (a === '-s' || a === '--static') o.static.push(val());
    else if (a.startsWith('-') && a !== '-') throw new Error(`Unknown option: ${a}`);
    else if (o.file === null) o.file = a;
    else throw new Error(`Unexpected argument: ${a}`);
  }
  return o;
}

function main(argv) {
  let opts;
  try { opts = parseArgs(argv); } catch (e) { console.error(e.message + '\n\n' + USAGE); return process.exit(1); }
  if (opts.help) { console.log(USAGE); return process.exit(0); }
  if (!opts.file) { console.error(USAGE); return process.exit(1); }
  let store;
  try { store = new Store(opts.file); } catch (e) {
    console.error(`Cannot load database ${opts.file}: ${e.message}`);
    return process.exit(1);
  }
  const dirs = [...opts.static];
  const pub = path.resolve('public');
  if (fs.existsSync(pub) && fs.statSync(pub).isDirectory() && !dirs.some((d) => path.resolve(d) === pub)) dirs.push(pub);
  const server = createServer(store, { staticDirs: dirs });
  server.on('error', (e) => { console.error(`Server error: ${e.message}`); process.exit(1); });
  server.listen(opts.port, opts.host, () => {
    const port = server.address().port;
    console.log(`JSON Server started on PORT :${port}`);
    console.log(`http://${opts.host}:${port}`);
  });
  const stop = () => { server.close(() => process.exit(0)); setTimeout(() => process.exit(0), 500).unref(); };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}

module.exports = { main, parseArgs };
