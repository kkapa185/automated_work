"""Inline parsing (delimiter-run algorithm, links, code spans, raw HTML...)."""
import re
from bisect import bisect_right

from .node import Node
from .util import (ASCII_PUNCT, ENTITY_RE, decode_entity, is_punct, is_ws,
                   normalize_label, unescape_string)

# --------------------------------------------------------------------------
# Link helpers (shared with the block parser for reference definitions)
# --------------------------------------------------------------------------
_LABEL_RE = re.compile(r'\[[^\\\[\]]*(?:\\.[^\\\[\]]*)*\]', re.S)
_SPNL_RE = re.compile(r'[ \t]*(?:\n[ \t]*)?')
_EOL_RE = re.compile(r'[ \t]*(?:\n|\Z)')
_DEST_CHUNK = re.compile(r'[^()\\\x00-\x20\x7f]*')
_TITLE_RES = {
    '"': re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"', re.S),
    "'": re.compile(r"'([^'\\]*(?:\\.[^'\\]*)*)'", re.S),
    '(': re.compile(r'\(([^()\\]*(?:\\.[^()\\]*)*)\)', re.S),
}


def parse_link_label(s, pos):
    """Length of a link label ('[...]') at pos, or 0."""
    if pos >= len(s) or s[pos] != '[':
        return 0
    m = _LABEL_RE.match(s, pos, pos + 1002)
    if m is None:
        return 0
    n = m.end() - pos
    return n if n - 2 <= 999 else 0


def spnl(s, pos):
    return _SPNL_RE.match(s, pos).end()


def parse_link_destination(s, pos):
    """Return (raw_destination, newpos) or None."""
    n = len(s)
    if pos < n and s[pos] == '<':
        i = pos + 1
        while i < n:
            c = s[i]
            if c == '>':
                return s[pos + 1:i], i + 1
            if c == '\n' or c == '<':
                return None
            if c == '\\' and i + 1 < n and s[i + 1] in ASCII_PUNCT:
                i += 2
            else:
                i += 1
        return None
    i = pos
    depth = 0
    while i < n:
        i = _DEST_CHUNK.match(s, i).end()
        if i >= n:
            break
        c = s[i]
        if c == '\\':
            if i + 1 < n and s[i + 1] in ASCII_PUNCT:
                i += 2
            else:
                i += 1
        elif c == '(':
            depth += 1
            if depth > 32:
                return None
            i += 1
        elif c == ')':
            if depth == 0:
                break
            depth -= 1
            i += 1
        else:  # whitespace or control character
            break
    if depth != 0:
        return None
    return s[pos:i], i


def parse_link_title(s, pos):
    """Return (raw_title, newpos) or None."""
    if pos >= len(s):
        return None
    rx = _TITLE_RES.get(s[pos])
    if rx is None:
        return None
    m = rx.match(s, pos)
    if m is None:
        return None
    return m.group(1), m.end()


def parse_reference(s, pos, refmap):
    """Parse a link reference definition at s[pos:]; return new pos or None.
    On success the definition is recorded in refmap (first one wins)."""
    n = parse_link_label(s, pos)
    if n == 0:
        return None
    label = s[pos + 1:pos + n - 1]
    i = pos + n
    if i >= len(s) or s[i] != ':':
        return None
    i = spnl(s, i + 1)
    d = parse_link_destination(s, i)
    if d is None:
        return None
    dest, j = d
    if dest == '' and not s.startswith('<', i):
        return None
    before = j
    k = spnl(s, j)
    title = None
    if k != j:
        t = parse_link_title(s, k)
        if t is not None:
            title, j = t
    m = _EOL_RE.match(s, j)
    if m is None:
        if title is None:
            return None
        title = None
        m = _EOL_RE.match(s, before)
        if m is None:
            return None
    norm = normalize_label(label)
    if norm == '':
        return None
    if norm not in refmap:
        refmap[norm] = (unescape_string(dest),
                        unescape_string(title) if title is not None else '')
    return m.end()


# --------------------------------------------------------------------------
# Raw HTML / autolink patterns
# --------------------------------------------------------------------------
_WS = r'[ \t\n\r\f\v]'
_ATTR = (r'(?:' + _WS + r'+[A-Za-z_:][A-Za-z0-9_.:\-]*(?:' + _WS + r'*=' + _WS +
         r'*(?:[^ \t\n\r\f\v"\'=<>`]+|\'[^\']*\'|"[^"]*"))?)')
OPEN_TAG_RE = re.compile(r'<[A-Za-z][A-Za-z0-9\-]*' + _ATTR + r'*' + _WS + r'*/?>')
CLOSE_TAG_RE = re.compile(r'</[A-Za-z][A-Za-z0-9\-]*' + _WS + r'*>')
AUTOLINK_RE = re.compile(r'<([A-Za-z][A-Za-z0-9.+\-]{1,31}:[^\x00-\x20<>]*)>')
EMAIL_RE = re.compile(
    r"<([a-zA-Z0-9.!#$%&'*+/=?^_`{|}~\-]+@[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}"
    r"[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*)>")
_SPECIAL = re.compile(r'[\n\\`*_\[\]<&!\'"]')
_SPECIAL_SMART = re.compile(r'[\n\\`*_\[\]<&!\'".\-]')
_BACKTICKS = re.compile(r'`+')
_HYPHENS = re.compile(r'-+')

LDQUO, RDQUO, LSQUO, RSQUO = '“', '”', '‘', '’'


class Delim:
    __slots__ = ('cc', 'numdelims', 'orig', 'node', 'prev', 'next',
                 'can_open', 'can_close')


class Bracket:
    __slots__ = ('node', 'prev', 'prev_delim', 'index', 'image',
                 'bracket_after', 'lidx')


class InlineParser:
    def __init__(self, refmap, smart=False):
        self.refmap = refmap
        self.smart = smart

    # -- public --------------------------------------------------------
    def parse(self, parent, text):
        self.s = s = text
        self.parent = parent
        self.delimiters = None
        self.brackets = None
        self.buf = []
        self.runs = None
        self.nofind = {}
        self.link_openers = 0      # count of non-image brackets on the stack
        self.inactive_below = 0    # non-image brackets with index < this are inactive
        special = _SPECIAL_SMART if self.smart else _SPECIAL
        n = len(s)
        pos = 0
        buf = self.buf
        while pos < n:
            c = s[pos]
            if c == '\n':
                pos = self.handle_newline(pos)
            elif c == '\\':
                pos = self.handle_backslash(pos)
            elif c == '`':
                pos = self.handle_backticks(pos)
            elif c == '*' or c == '_':
                pos = self.handle_delim(pos, c)
            elif c == "'" or c == '"':
                if self.smart:
                    pos = self.handle_delim(pos, c)
                else:
                    buf.append(c)
                    pos += 1
            elif c == '[':
                self.flush()
                node = Node('text', '[')
                parent.append_child(node)
                self.push_bracket(node, pos + 1, False)
                pos += 1
            elif c == '!':
                if pos + 1 < n and s[pos + 1] == '[':
                    self.flush()
                    node = Node('text', '![')
                    parent.append_child(node)
                    self.push_bracket(node, pos + 2, True)
                    pos += 2
                else:
                    buf.append('!')
                    pos += 1
            elif c == ']':
                pos = self.handle_close_bracket(pos)
            elif c == '<':
                pos = self.handle_lt(pos)
            elif c == '&':
                m = ENTITY_RE.match(s, pos)
                r = decode_entity(m.group()) if m else None
                if r is not None:
                    buf.append(r)
                    pos = m.end()
                else:
                    buf.append('&')
                    pos += 1
            elif c == '.' and self.smart:
                if s.startswith('...', pos):
                    buf.append('…')
                    pos += 3
                else:
                    buf.append('.')
                    pos += 1
            elif c == '-' and self.smart:
                m = _HYPHENS.match(s, pos)
                k = m.end() - pos
                if k == 1:
                    buf.append('-')
                else:
                    if k % 3 == 0:
                        em, en = k // 3, 0
                    elif k % 2 == 0:
                        em, en = 0, k // 2
                    elif k % 3 == 2:
                        em, en = (k - 2) // 3, 1
                    else:
                        em, en = (k - 4) // 3, 2
                    buf.append('—' * em + '–' * en)
                pos = m.end()
            else:
                m = special.search(s, pos + 1)
                end = m.start() if m else n
                buf.append(s[pos:end])
                pos = end
        self.flush()
        self.process_emphasis(None)

    def flush(self):
        if self.buf:
            self.parent.append_child(Node('text', ''.join(self.buf)))
            self.buf.clear()

    # -- simple constructs ----------------------------------------------
    def skip_spaces(self, pos):
        s = self.s
        n = len(s)
        while pos < n and s[pos] == ' ':
            pos += 1
        return pos

    def handle_newline(self, pos):
        text = ''.join(self.buf)
        self.buf.clear()
        hard = False
        if text.endswith(' '):
            stripped = text.rstrip(' ')
            hard = len(text) - len(stripped) >= 2
            text = stripped
        if text:
            self.parent.append_child(Node('text', text))
        self.parent.append_child(Node('linebreak' if hard else 'softbreak'))
        return self.skip_spaces(pos + 1)

    def handle_backslash(self, pos):
        s = self.s
        nxt = s[pos + 1] if pos + 1 < len(s) else ''
        if nxt == '\n':
            self.flush()
            self.parent.append_child(Node('linebreak'))
            return self.skip_spaces(pos + 2)
        if nxt and nxt in ASCII_PUNCT:
            self.buf.append(nxt)
            return pos + 2
        self.buf.append('\\')
        return pos + 1

    def handle_backticks(self, pos):
        s = self.s
        n = _BACKTICKS.match(s, pos).end() - pos
        if self.runs is None:
            runs = {}
            for m in _BACKTICKS.finditer(s):
                runs.setdefault(m.end() - m.start(), []).append(m.start())
            self.runs = runs
        lst = self.runs.get(n)
        if lst:
            i = bisect_right(lst, pos)
            if i < len(lst):
                q = lst[i]
                content = s[pos + n:q].replace('\n', ' ')
                if (len(content) >= 2 and content[0] == ' ' and
                        content[-1] == ' ' and content.strip(' ') != ''):
                    content = content[1:-1]
                self.flush()
                self.parent.append_child(Node('code', content))
                return q + n
        self.buf.append('`' * n)
        return pos + n

    def handle_lt(self, pos):
        s = self.s
        m = AUTOLINK_RE.match(s, pos)
        if m:
            self.flush()
            node = Node('link')
            node.dest = m.group(1)
            node.title = ''
            node.append_child(Node('text', m.group(1)))
            self.parent.append_child(node)
            return m.end()
        m = EMAIL_RE.match(s, pos)
        if m:
            self.flush()
            node = Node('link')
            node.dest = 'mailto:' + m.group(1)
            node.title = ''
            node.append_child(Node('text', m.group(1)))
            self.parent.append_child(node)
            return m.end()
        end = self.match_html(pos)
        if end > 0:
            self.flush()
            self.parent.append_child(Node('html_inline', s[pos:end]))
            return end
        self.buf.append('<')
        return pos + 1

    def find_end(self, token, start):
        """str.find with memoised failure (keeps scans linear overall)."""
        failed = self.nofind.get(token)
        if failed is not None and failed <= start:
            return -1
        i = self.s.find(token, start)
        if i < 0:
            self.nofind[token] = start if failed is None else min(failed, start)
        return i

    def match_html(self, pos):
        """Return end index of raw HTML starting at pos, or -1."""
        s = self.s
        if pos + 1 >= len(s):
            return -1
        c = s[pos + 1]
        if c == '/':
            m = CLOSE_TAG_RE.match(s, pos)
            return m.end() if m else -1
        if c == '?':
            i = self.find_end('?>', pos + 2)
            return i + 2 if i >= 0 else -1
        if c == '!':
            if s.startswith('<!--', pos):
                if s.startswith('<!-->', pos):
                    return pos + 5
                if s.startswith('<!--->', pos):
                    return pos + 6
                i = self.find_end('-->', pos + 4)
                return i + 3 if i >= 0 else -1
            if s.startswith('<![CDATA[', pos):
                i = self.find_end(']]>', pos + 9)
                return i + 3 if i >= 0 else -1
            if pos + 2 < len(s) and 'A' <= s[pos + 2] <= 'Z' or \
                    pos + 2 < len(s) and 'a' <= s[pos + 2] <= 'z':
                i = self.find_end('>', pos + 3)
                return i + 1 if i >= 0 else -1
            return -1
        if ('a' <= c <= 'z') or ('A' <= c <= 'Z'):
            m = OPEN_TAG_RE.match(s, pos)
            return m.end() if m else -1
        return -1

    # -- delimiters --------------------------------------------------------
    def handle_delim(self, pos, c):
        s = self.s
        n = len(s)
        if c == '*' or c == '_':
            end = pos
            while end < n and s[end] == c:
                end += 1
            numdelims = end - pos
        else:
            numdelims = 1
            end = pos + 1
        before = s[pos - 1] if pos > 0 else '\n'
        after = s[end] if end < n else '\n'
        after_ws = is_ws(after)
        after_p = is_punct(after)
        before_ws = is_ws(before)
        before_p = is_punct(before)
        left = (not after_ws) and ((not after_p) or before_ws or before_p)
        right = (not before_ws) and ((not before_p) or after_ws or after_p)
        if c == '_':
            can_open = left and ((not right) or before_p)
            can_close = right and ((not left) or after_p)
        elif c == "'" or c == '"':
            can_open = left and (not right) and before != ']' and before != ')'
            can_close = right
        else:
            can_open = left
            can_close = right
        self.flush()
        if c == "'":
            text = RSQUO
        elif c == '"':
            text = LDQUO
        else:
            text = s[pos:end]
        node = Node('text', text)
        self.parent.append_child(node)
        if can_open or can_close:
            d = Delim()
            d.cc = c
            d.numdelims = d.orig = numdelims
            d.node = node
            d.prev = self.delimiters
            d.next = None
            d.can_open = can_open
            d.can_close = can_close
            if d.prev is not None:
                d.prev.next = d
            self.delimiters = d
        return end

    def remove_delimiter(self, d):
        if d.prev is not None:
            d.prev.next = d.next
        if d.next is None:
            self.delimiters = d.prev
        else:
            d.next.prev = d.prev

    def process_emphasis(self, stack_bottom):
        openers_bottom = {}
        # find first delimiter above stack_bottom
        closer = self.delimiters
        if closer is stack_bottom:
            closer = None
        while closer is not None and closer.prev is not stack_bottom:
            closer = closer.prev
        while closer is not None:
            if not closer.can_close:
                closer = closer.next
                continue
            cc = closer.cc
            key = (cc, closer.can_open, closer.orig % 3)
            bottom = openers_bottom.get(key, stack_bottom)
            opener = closer.prev
            found = False
            while opener is not None and opener is not stack_bottom and opener is not bottom:
                if opener.cc == cc and opener.can_open:
                    odd = ((closer.can_open or opener.can_close) and
                           closer.orig % 3 != 0 and
                           (opener.orig + closer.orig) % 3 == 0)
                    if not odd:
                        found = True
                        break
                opener = opener.prev
            old_closer = closer
            if cc == '*' or cc == '_':
                if not found:
                    closer = closer.next
                else:
                    use = 2 if (closer.numdelims >= 2 and opener.numdelims >= 2) else 1
                    o_node = opener.node
                    c_node = closer.node
                    opener.numdelims -= use
                    closer.numdelims -= use
                    o_node.literal = o_node.literal[:-use]
                    c_node.literal = c_node.literal[:-use]
                    emph = Node('strong' if use == 2 else 'emph')
                    tmp = o_node.next
                    while tmp is not None and tmp is not c_node:
                        nxt = tmp.next
                        tmp.unlink()
                        emph.append_child(tmp)
                        tmp = nxt
                    o_node.insert_after(emph)
                    # drop delimiters between opener and closer
                    opener.next = closer
                    closer.prev = opener
                    if opener.numdelims == 0:
                        o_node.unlink()
                        self.remove_delimiter(opener)
                    if closer.numdelims == 0:
                        c_node.unlink()
                        nxt = closer.next
                        self.remove_delimiter(closer)
                        closer = nxt
            else:  # smart quotes
                if cc == "'":
                    closer.node.literal = RSQUO
                    if found:
                        opener.node.literal = LSQUO
                else:
                    closer.node.literal = RDQUO
                    if found:
                        opener.node.literal = LDQUO
                nxt = closer.next
                if found:
                    opener.next = closer
                    closer.prev = opener
                    self.remove_delimiter(opener)
                    self.remove_delimiter(closer)
                closer = nxt
            if not found:
                openers_bottom[key] = old_closer.prev
                if not old_closer.can_open:
                    self.remove_delimiter(old_closer)
        # remove all delimiters above stack_bottom
        self.delimiters = stack_bottom
        if stack_bottom is not None:
            stack_bottom.next = None

    # -- brackets ------------------------------------------------------------
    def push_bracket(self, node, index, image):
        if self.brackets is not None:
            self.brackets.bracket_after = True
        b = Bracket()
        b.node = node
        b.prev = self.brackets
        b.prev_delim = self.delimiters
        b.index = index
        b.image = image
        b.bracket_after = False
        if image:
            b.lidx = -1
        else:
            b.lidx = self.link_openers
            self.link_openers += 1
        self.brackets = b

    def pop_bracket(self):
        b = self.brackets
        self.brackets = b.prev
        if not b.image:
            self.link_openers -= 1
            if self.inactive_below > self.link_openers:
                self.inactive_below = self.link_openers

    def try_inline_link(self, pos):
        """pos is at '('. Return (dest, title, newpos) or None."""
        s = self.s
        i = spnl(s, pos + 1)
        d = parse_link_destination(s, i)
        if d is None:
            return None
        dest, j = d
        title = ''
        k = spnl(s, j)
        if k != j:
            t = parse_link_title(s, k)
            if t is not None:
                title = unescape_string(t[0])
                k = spnl(s, t[1])
        if k < len(s) and s[k] == ')':
            return unescape_string(dest), title, k + 1
        return None

    def handle_close_bracket(self, pos):
        s = self.s
        self.flush()
        opener = self.brackets
        if opener is None:
            self.buf.append(']')
            return pos + 1
        if not opener.image and opener.lidx < self.inactive_below:
            self.pop_bracket()
            self.buf.append(']')
            return pos + 1
        after = pos + 1
        dest = title = None
        matched = False
        if after < len(s) and s[after] == '(':
            r = self.try_inline_link(after)
            if r is not None:
                dest, title, after = r
                matched = True
        if not matched:
            n = parse_link_label(s, after)
            reflabel = None
            if n > 2:
                reflabel = s[after:after + n][1:-1]
            elif not opener.bracket_after:
                if pos - opener.index <= 999:
                    reflabel = s[opener.index:pos]
            if reflabel:
                ref = self.refmap.get(normalize_label(reflabel))
                if ref is not None:
                    dest, title = ref
                    matched = True
                    if n > 0:
                        after = after + n
        if matched:
            node = Node('image' if opener.image else 'link')
            node.dest = dest
            node.title = title
            tmp = opener.node.next
            while tmp is not None:
                nxt = tmp.next
                tmp.unlink()
                node.append_child(tmp)
                tmp = nxt
            self.parent.append_child(node)
            self.process_emphasis(opener.prev_delim)
            self.pop_bracket()
            opener.node.unlink()
            if not opener.image:
                # links may not contain other links: deactivate earlier '['
                self.inactive_below = self.link_openers
            return after
        self.pop_bracket()
        self.buf.append(']')
        return pos + 1
