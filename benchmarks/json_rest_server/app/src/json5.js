'use strict';
// Minimal JSON5 parser (superset of JSON): comments, unquoted/single-quoted keys and strings,
// trailing commas, hex/leading-dot/trailing-dot/signed numbers, Infinity, NaN, line continuations.

const WS = /[\s\u00a0\ufeff\u2028\u2029]/;
const ID_START = /[\p{L}\p{Nl}$_]/u;
const ID_PART = /[\p{L}\p{Nl}\p{Mn}\p{Mc}\p{Nd}\p{Pc}$_‌‍]/u;

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

  function value() {
    skip();
    const c = text[i];
    if (c === '{') return object();
    if (c === '[') return array();
    if (c === '"' || c === "'") return string();
    if (c === undefined) fail('unexpected end of input');
    return literal();
  }

  function literal() {
    const rest = text.slice(i, i + 9);
    for (const [word, val] of [['true', true], ['false', false], ['null', null], ['Infinity', Infinity], ['NaN', NaN]]) {
      if (rest.startsWith(word) && !isIdPart(text[i + word.length])) { i += word.length; return val; }
    }
    return number();
  }

  function isIdPart(c) { return c !== undefined && ID_PART.test(c); }

  function number() {
    let sign = 1;
    if (text[i] === '+' || text[i] === '-') { if (text[i] === '-') sign = -1; i++; }
    if (text.startsWith('Infinity', i)) { i += 8; return sign * Infinity; }
    if (text.startsWith('NaN', i)) { i += 3; return NaN; }
    const hex = /^0[xX][0-9a-fA-F]+/.exec(text.slice(i, i + 40));
    if (hex) { i += hex[0].length; return sign * Number(hex[0]); }
    const m = /^(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/.exec(text.slice(i, i + 400));
    if (!m) fail(`unexpected character ${JSON.stringify(text[i])}`);
    i += m[0].length;
    return sign * Number(m[0]);
  }

  function string() {
    const q = text[i++];
    let out = '';
    for (;;) {
      const c = text[i];
      if (c === undefined) fail('unterminated string');
      if (c === q) { i++; return out; }
      if (c === '\\') {
        i++;
        const e = text[i++];
        switch (e) {
          case 'n': out += '\n'; break;
          case 't': out += '\t'; break;
          case 'r': out += '\r'; break;
          case 'b': out += '\b'; break;
          case 'f': out += '\f'; break;
          case 'v': out += '\v'; break;
          case '0': out += '\0'; break;
          case 'x': out += hexEsc(2); break;
          case 'u': out += hexEsc(4); break;
          case '\r': if (text[i] === '\n') i++; break;
          case '\n': case '\u2028': case '\u2029': break;
          case undefined: fail('unterminated string');
          default: out += e;
        }
        continue;
      }
      if (c === '\n' || c === '\r') fail('unescaped newline in string');
      out += c;
      i++;
    }
  }

  function hexEsc(len) {
    const h = text.slice(i, i + len);
    if (!new RegExp(`^[0-9a-fA-F]{${len}}$`).test(h)) fail('invalid escape');
    i += len;
    return String.fromCharCode(parseInt(h, 16));
  }

  function key() {
    skip();
    const c = text[i];
    if (c === '"' || c === "'") return string();
    let out = '';
    while (i < n) {
      if (text[i] === '\\' && text[i + 1] === 'u') { i += 2; out += hexEsc(4); continue; }
      const ch = String.fromCodePoint(text.codePointAt(i));
      if (!(out === '' ? ID_START : ID_PART).test(ch)) break;
      out += ch;
      i += ch.length;
    }
    if (!out) fail('expected property name');
    return out;
  }

  function object() {
    i++;
    const obj = {};
    for (;;) {
      skip();
      if (text[i] === '}') { i++; return obj; }
      const k = key();
      skip();
      if (text[i] !== ':') fail("expected ':'");
      i++;
      Object.defineProperty(obj, k, { value: value(), enumerable: true, writable: true, configurable: true });
      skip();
      if (text[i] === ',') { i++; continue; }
      if (text[i] === '}') { i++; return obj; }
      fail("expected ',' or '}'");
    }
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

  const result = value();
  skip();
  if (i < n) fail('unexpected trailing content');
  return result;
}

module.exports = { parse };
