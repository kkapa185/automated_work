"""Shared helpers: character classes, escaping, entities, URL handling."""
import re
import unicodedata
from functools import lru_cache
from html.entities import html5 as _HTML5

ASCII_PUNCT = frozenset('!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~')

_ENTITY_BODY = r'&(?:#[xX][0-9a-fA-F]{1,6}|#[0-9]{1,7}|[A-Za-z][A-Za-z0-9]{1,31});'
ENTITY_RE = re.compile(_ENTITY_BODY)
_UNESCAPE_RE = re.compile(r'\\([!-/:-@\[-`{-~])|(' + _ENTITY_BODY + ')')


@lru_cache(maxsize=None)
def is_punct(c):
    """Unicode punctuation (P* or S*) or ASCII punctuation."""
    if c in ASCII_PUNCT:
        return True
    return unicodedata.category(c)[0] in 'PS'


@lru_cache(maxsize=None)
def is_ws(c):
    """Unicode whitespace: Zs, tab, LF, FF, CR."""
    if c in '\t\n\f\r ':
        return True
    return unicodedata.category(c) == 'Zs'


def decode_entity(text):
    """Decode '&...;' (already validated syntactically); None if unknown."""
    if text[1] == '#':
        if text[2] in 'xX':
            n = int(text[3:-1], 16)
        else:
            n = int(text[2:-1])
        if n == 0 or n > 0x10FFFF or 0xD800 <= n <= 0xDFFF:
            return '\ufffd'
        return chr(n)
    return _HTML5.get(text[1:])


def _unescape_cb(m):
    if m.group(1) is not None:
        return m.group(1)
    r = decode_entity(m.group(2))
    return m.group(2) if r is None else r


def unescape_string(s):
    """Process backslash escapes and entity references."""
    if '\\' not in s and '&' not in s:
        return s
    return _UNESCAPE_RE.sub(_unescape_cb, s)


_ESC_TABLE = {ord('&'): '&amp;', ord('<'): '&lt;', ord('>'): '&gt;',
              ord('"'): '&quot;'}


def escape_html(s):
    return s.translate(_ESC_TABLE)


_HREF_UNSAFE = re.compile(r"[^A-Za-z0-9!#$%()*+,\-./:;=?@_~]+")


def _href_cb(m):
    out = []
    for ch in m.group(0):
        if ch == '&':
            out.append('&amp;')
        elif ch == "'":
            out.append('&#x27;')
        else:
            out.extend('%%%02X' % b for b in ch.encode('utf-8', 'replace'))
    return ''.join(out)


def escape_href(s):
    return _HREF_UNSAFE.sub(_href_cb, s)


_WS_RUN = re.compile(r'[ \t\r\n\f\v]+')


def normalize_label(s):
    """Normalize a link label: trim, collapse whitespace, Unicode case fold."""
    return _WS_RUN.sub(' ', s.strip(' \t\r\n\f\v')).casefold()


_DANGEROUS = re.compile(r'(?i)(?:javascript|vbscript|file):|data:(?!image/(?:png|gif|jpeg|webp))')


def is_dangerous_url(url):
    return _DANGEROUS.match(url) is not None
