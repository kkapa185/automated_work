'use strict';
const fs = require('node:fs');
const { createApp } = require('./app');

const HELP = `Usage: serve <db.json|db.json5> [options]

Options:
  -p, --port <port>     Port (default: 3000)
  -H, --host <host>     Host (default: 127.0.0.1)
  -s, --static <dir>    Static files directory (repeatable; ./public is served if it exists)
  -h, --help            Show this help
`;

function parseArgs(argv) {
  const o = { port: 3000, host: '127.0.0.1', statics: [], file: null, help: false };
  for (let i = 0; i < argv.length; i++) {
    let a = argv[i], inline;
    if (a.startsWith('--') && a.includes('=')) { inline = a.slice(a.indexOf('=') + 1); a = a.slice(0, a.indexOf('=')); }
    const val = () => {
      if (inline !== undefined) return inline;
      if (i + 1 >= argv.length) throw new Error(`Missing value for ${a}`);
      return argv[++i];
    };
    if (a === '-h' || a === '--help') o.help = true;
    else if (a === '-p' || a === '--port') {
      const v = val();
      if (!/^\d+$/.test(v) || Number(v) > 65535) throw new Error(`Invalid port: ${v}`);
      o.port = Number(v);
    } else if (a === '-H' || a === '--host') o.host = val();
    else if (a === '-s' || a === '--static') o.statics.push(val());
    else if (a.startsWith('-') && a.length > 1) throw new Error(`Unknown option: ${a}`);
    else if (o.file === null) o.file = a;
    else throw new Error(`Unexpected argument: ${a}`);
  }
  return o;
}

function main(argv) {
  let o;
  try { o = parseArgs(argv); } catch (e) { console.error(e.message + '\n' + HELP); return 1; }
  if (o.help) { console.log(HELP); return 0; }
  if (!o.file) { console.error('Missing database file\n' + HELP); return 1; }
  const staticDirs = [...o.statics];
  if (fs.existsSync('./public') && fs.statSync('./public').isDirectory() && !staticDirs.includes('./public')) {
    staticDirs.unshift('./public');
  }
  let app;
  try { app = createApp({ dbPath: o.file, staticDirs }); } catch (e) {
    console.error(`Cannot load ${o.file}: ${e.message}`);
    return 1;
  }
  app.server.on('error', (e) => { console.error(e.message); process.exit(1); });
  app.server.listen(o.port, o.host, () => {
    const port = app.server.address().port;
    console.log(`JSON Server started on PORT :${port}`);
    console.log(`http://${o.host}:${port}`);
  });
  const stop = () => app.server.close(() => process.exit(0));
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  return null;
}

if (require.main === module || process.env.SERVE_MAIN) {
  const code = main(process.argv.slice(2));
  if (code !== null) process.exit(code);
}
module.exports = { main, parseArgs };
