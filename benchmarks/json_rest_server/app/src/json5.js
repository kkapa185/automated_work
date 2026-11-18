'use strict';
// Minimal JSON5 parser (superset of JSON): comments, unquoted keys, single quotes,
// trailing commas, hex numbers, +/- signs, Infinity/NaN, line continuations.

const WS = /[\s\uFEFF\u2028\u2029]/;
const ID_START = /[A-Za-z_$\u00A0-\uFFFF]/;
const ID_PART = /[A-Za-z0-9_$\u00A0-\uFFFF\u200C\u200D]/;

function parse(text) {
  let i = 0;
  const n = text.length;

  function fail(msg) {
    let line = 1, col = 1;
    for (let k = 0; k < i && k < n; k++) {
      if (text[k] === '\n') { line++; col = 1; } else col++;
    }
    throw new SyntaxError(`JSON5: ${msg} at line ${line} column ${col}`);
  }

  function skip() {
    for (;;) {
      const c = text[i];
      if (c === undefined) return;
      if (WS.test(c)) { i++; continue; }
      if (c === '/' && text[i + 1] === '/') {
        i += 2;
        while (i < n && text[i] !== '\n' && text[i] !== '\r' && text[i] !== '\u2028' && text[i] !== '\u2029') i++;
        continue;
      }
      if (c === '/' && text[i + 1] === '*') {
        const end = text.indexOf('*/', i + 2);
        if (end < 0) fail('unterminated comment');
        i = end + 2;
        continue;
      }
      return;
    }
  }

  function setKey(obj, k, v) {
    Object.defineProperty(obj, k, { value: v, writable: true, enumerable: true, configurable: true });
  }

  function value() {
    skip();
    const c = text[i];
    if (c === undefined) fail('unexpected end of input');
    if (c === '{') return object();
    if (c === '[') return array();
    if (c === '"' || c === "'") return string();
    if (c === '-' || c === '+' || c === '.' || (c >= '0' && c <= '9') || c === 'I' || c === 'N') return number();
    if (text.startsWith('true', i) && !ID_PART.test(text[i + 4] || ' ')) { i += 4; return true; }
    if (text.startsWith('false', i) && !ID_PART.test(text[i + 5] || ' ')) { i += 5; return false; }
    if (text.startsWith('null', i) && !ID_PART.test(text[i + 4] || ' ')) { i += 4; return null; }
    fail(`unexpected character ${JSON.stringify(c)}`);
  }

  function object() {
    i++;
    const obj = {};
    for (;;) {
      skip();
      if (text[i] === '}') { i++; return obj; }
      let key;
      const c = text[i];
      if (c === '"' || c === "'") key = string();
      else if (c !== undefined && (ID_START.test(c) || c === '\\')) key = ident();
      else fail('expected property name');
      skip();
      if (text[i] !== ':') fail("expected ':'");
      i++;
      setKey(obj, key, value());
      skip();
      if (text[i] === ',') { i++; continue; }
      if (text[i] === '}') { i++; return obj; }
      fail("expected ',' or '}'");
    }
  }

  function ident() {
    let s = '';
    while (i < n) {
      const c = text[i];
      if (c === '\\') {
        if (text[i + 1] !== 'u') fail('invalid identifier escape');
        const h = text.slice(i + 2, i + 6);
        if (!/^[0-9a-fA-F]{4}$/.test(h)) fail('invalid unicode escape');
        s += String.fromCharCode(parseInt(h, 16));
        i += 6;
      } else if (ID_PART.test(c)) { s += c; i++; } else break;
    }
    if (!s) fail('invalid identifier');
    return s;
  }

  function array() {
    i++;
    const arr = [];
    for (;;) {
      skip();
      if (text[i] === ']') { i++; return arr; }
      arr.push(value());
      skip();
      if (text[i] === ',') { i++; continue; }
      if (text[i] === ']') { i++; return arr; }
      fail("expected ',' or ']'");
    }
  }

  function string() {
    const q = text[i++];
    let s = '';
    for (;;) {
      if (i >= n) fail('unterminated string');
      const c = text[i++];
      if (c === q) return s;
      if (c === '\n' || c === '\r') { i--; fail('unescaped newline in string'); }
      if (c !== '\\') { s += c; continue; }
      const e = text[i++];
      switch (e) {
        case 'n': s += '\n'; break;
        case 't': s += '\t'; break;
        case 'r': s += '\r'; break;
        case 'b': s += '\b'; break;
        case 'f': s += '\f'; break;
        case 'v': s += '\v'; break;
        case '0':
          if (text[i] >= '0' && text[i] <= '9') fail('invalid octal escape');
          s += '\0'; break;
        case 'x': {
          const h = text.slice(i, i + 2);
          if (!/^[0-9a-fA-F]{2}$/.test(h)) fail('invalid hex escape');
          s += String.fromCharCode(parseInt(h, 16)); i += 2; break;
        }
        case 'u': {
          const h = text.slice(i, i + 4);
          if (!/^[0-9a-fA-F]{4}$/.test(h)) fail('invalid unicode escape');
          s += String.fromCharCode(parseInt(h, 16)); i += 4; break;
        }
        case '\r': if (text[i] === '\n') i++; break;
        case '\n': case '\u2028': case '\u2029': break;
        case undefined: fail('unterminated string');
        default:
          if (e >= '1' && e <= '9') fail('invalid escape');
          s += e;
      }
    }
  }

  function number() {
    const m = /^[+-]?(?:Infinity|NaN|0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)/.exec(text.slice(i, i + 400));
    if (!m) fail('invalid number');
    i += m[0].length;
    let t = m[0];
    let sign = 1;
    if (t[0] === '-') { sign = -1; t = t.slice(1); } else if (t[0] === '+') t = t.slice(1);
    if (t === 'Infinity') return sign * Infinity;
    if (t === 'NaN') return NaN;
    if (/^0[xX]/.test(t)) return sign * parseInt(t, 16);
    return sign * Number(t);
  }

  skip();
  const v = value();
  skip();
  if (i < n) fail('unexpected trailing content');
  return v;
}

module.exports = { parse };
