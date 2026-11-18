"""Block structure parser (line-by-line, open-container stack)."""
import re

from .inlines import InlineParser, parse_reference
from .node import Node
from .util import unescape_string

_TAGS6 = ('address|article|aside|base|basefont|blockquote|body|caption|center|'
          'col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|'
          'figure|footer|form|frame|frameset|h1|h2|h3|h4|h5|h6|head|header|hr|'
          'html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|'
          'optgroup|option|p|param|search|section|summary|table|tbody|td|'
          'tfoot|th|thead|title|tr|track|ul')
_WS = r'[ \t\n\r\f\v]'
_ATTR = (r'(?:' + _WS + r'+[A-Za-z_:][A-Za-z0-9_.:\-]*(?:' + _WS + r'*=' + _WS +
         r'*(?:[^ \t\n\r\f\v"\'=<>`]+|\'[^\']*\'|"[^"]*"))?)')
_OPEN = r'<[A-Za-z][A-Za-z0-9\-]*' + _ATTR + r'*' + _WS + r'*/?>'
_CLOSE = r'</[A-Za-z][A-Za-z0-9\-]*' + _WS + r'*>'

HTML_OPEN = [
    None,
    re.compile(r'<(?:script|pre|style|textarea)(?:[ \t\n\r\f\v>]|\Z)', re.I),
    re.compile(r'<!--'),
    re.compile(r'<\?'),
    re.compile(r'<![A-Za-z]'),
    re.compile(r'<!\[CDATA\['),
    re.compile(r'</?(?:' + _TAGS6 + r')(?:[ \t\n\r\f\v]|/?>|\Z)', re.I),
    re.compile(r'(?:' + _OPEN + '|' + _CLOSE + r')[ \t]*\Z'),
]
HTML_CLOSE = [
    None,
    re.compile(r'</(?:script|pre|style|textarea)>', re.I),
    re.compile(r'-->'),
    re.compile(r'\?>'),
    re.compile(r'>'),
    re.compile(r'\]\]>'),
]
_TYPE7_EXCL = re.compile(r'<(?:script|pre|style|textarea)[ \t\n\r\f\v/>]', re.I)

_MAYBE_SPECIAL = re.compile(r'[#`~*+_=<>0-9\-]')
_ATX = re.compile(r'#{1,6}(?:[ \t]+|\Z)')
_SETEXT = re.compile(r'(?:=+|-+)[ \t]*\Z')
_BULLET = re.compile(r'[*+\-]')
_ORDERED = re.compile(r'([0-9]{1,9})([.)])')
_CLOSE_FENCE = re.compile(r'(`{3,}|~{3,})[ \t]*\Z')
_NONBLANK = re.compile(r'[^ \t]')
_LINE_SPLIT = re.compile(r'\r\n|\n|\r')


class ListData:
    __slots__ = ('type', 'tight', 'bullet', 'start', 'delim', 'padding',
                 'marker_offset')


def _can_contain(parent_type, child_type):
    if parent_type in ('document', 'block_quote', 'item'):
        return child_type != 'item'
    if parent_type == 'list':
        return child_type == 'item'
    return False


class BlockParser:
    def __init__(self, smart=False):
        self.smart = smart
        self.doc = Node('document')
        self.doc.sl = self.doc.sc = 1
        self.tip = self.doc
        self.oldtip = self.doc
        self.last_matched = self.doc
        self.all_closed = True
        self.refmap = {}
        self.line_number = 0
        self.last_line_length = 0
        # per-line state
        self.line = ''
        self._hr_suffix = {}
        self._first_ns = None
        self.offset = self.column = 0
        self.next_nonspace = self.next_nonspace_column = 0
        self.indent = 0
        self.indented = False
        self.blank = False
        self.partial_tab = False

    # -- driver --------------------------------------------------------------
    def parse(self, text):
        lines = _LINE_SPLIT.split(text)
        if lines and lines[-1] == '':
            lines.pop()
        for ln in lines:
            self.incorporate_line(ln)
        total = len(lines)
        while self.tip is not None:
            self.finalize(self.tip, total)
        self.parse_inlines()
        return self.doc

    def parse_inlines(self):
        ip = InlineParser(self.refmap, self.smart)
        stack = [self.doc]
        while stack:
            node = stack.pop()
            t = node.type
            if t == 'paragraph' or t == 'heading':
                ip.parse(node, node.content)
            else:
                c = node.first_child
                while c is not None:
                    stack.append(c)
                    c = c.next

    # -- helpers ---------------------------------------------------------------
    def find_next_nonspace(self):
        ln = self.line
        n = len(ln)
        fn = self._first_ns
        if fn is None:
            # first non-whitespace position of the line, computed once per line
            i = 0
            cols = 0
            while i < n:
                c = ln[i]
                if c == ' ':
                    cols += 1
                elif c == '\t':
                    cols += 4 - (cols % 4)
                else:
                    break
                i += 1
            fn = self._first_ns = (i, cols)
        if self.offset <= fn[0]:
            i, cols = fn
        else:
            i = self.offset
            cols = self.column
            while i < n:
                c = ln[i]
                if c == ' ':
                    i += 1
                    cols += 1
                elif c == '\t':
                    i += 1
                    cols += 4 - (cols % 4)
                else:
                    break
        self.blank = i >= n
        self.next_nonspace = i
        self.next_nonspace_column = cols
        self.indent = cols - self.column
        self.indented = self.indent >= 4

    def advance_next_nonspace(self):
        self.offset = self.next_nonspace
        self.column = self.next_nonspace_column
        self.partial_tab = False

    def advance_offset(self, count, columns=False):
        ln = self.line
        n = len(ln)
        while count > 0 and self.offset < n:
            c = ln[self.offset]
            if c == '\t':
                to_tab = 4 - (self.column % 4)
                if columns:
                    self.partial_tab = to_tab > count
                    adv = to_tab if to_tab < count else count
                    self.column += adv
                    if not self.partial_tab:
                        self.offset += 1
                    count -= adv
                else:
                    self.partial_tab = False
                    self.column += to_tab
                    self.offset += 1
                    count -= 1
            else:
                self.partial_tab = False
                self.offset += 1
                self.column += 1
                count -= 1

    def add_line(self):
        ln = self.line
        tip = self.tip
        if tip.lines is None:
            tip.lines = []
        if self.partial_tab:
            self.offset += 1
            to_tab = 4 - (self.column % 4)
            tip.lines.append(' ' * to_tab + ln[self.offset:] + '\n')
        else:
            tip.lines.append(ln[self.offset:] + '\n')

    def add_child(self, type_, offset):
        while not _can_contain(self.tip.type, type_):
            self.finalize(self.tip, self.line_number - 1)
        node = Node(type_)
        node.sl = self.line_number
        node.sc = offset + 1
        self.tip.append_child(node)
        self.tip = node
        return node

    def close_unmatched(self):
        if not self.all_closed:
            old = self.oldtip
            lm = self.last_matched
            while old is not lm:
                parent = old.parent
                self.finalize(old, self.line_number - 1)
                old = parent
            self.all_closed = True

    # -- per-line --------------------------------------------------------------
    def incorporate_line(self, ln):
        self.line = ln
        self._hr_suffix = {}
        self._first_ns = None
        self.offset = self.column = 0
        self.blank = False
        self.partial_tab = False
        self.line_number += 1
        all_matched = True
        container = self.doc
        self.oldtip = self.tip
        while True:
            last = container.last_child
            if last is None or not last.open:
                break
            container = last
            self.find_next_nonspace()
            r = self.continue_block(container)
            if r == 0:
                continue
            if r == 1:
                all_matched = False
                container = container.parent
                break
            self.last_line_length = len(ln)  # r == 2: line fully consumed
            return
        self.all_closed = container is self.oldtip
        self.last_matched = container
        t = container.type
        matched_leaf = t != 'paragraph' and t in ('code_block', 'html_block')
        while not matched_leaf:
            self.find_next_nonspace()
            if not self.indented and not (
                    self.next_nonspace < len(ln) and
                    _MAYBE_SPECIAL.match(ln, self.next_nonspace)):
                self.advance_next_nonspace()
                break
            res = 0
            for start in self._starts:
                res = start(self, container)
                if res:
                    break
            if res == 1:
                container = self.tip
            elif res == 2:
                container = self.tip
                matched_leaf = True
            else:
                self.advance_next_nonspace()
                break
        if not self.all_closed and not self.blank and self.tip.type == 'paragraph':
            self.add_line()  # lazy continuation
        else:
            self.close_unmatched()
            if self.blank and container.last_child is not None:
                container.last_child.last_line_blank = True
            t = container.type
            lb = self.blank and not (
                t == 'block_quote' or (t == 'code_block' and container.fenced) or
                (t == 'item' and container.first_child is None and
                 container.sl == self.line_number))
            cont = container
            while cont is not None:
                cont.last_line_blank = lb
                cont = cont.parent
            if t == 'paragraph' or t == 'code_block' or t == 'html_block':
                self.add_line()
                if t == 'html_block' and 1 <= container.html_type <= 5 and \
                        HTML_CLOSE[container.html_type].search(ln, self.offset):
                    self.last_line_length = len(ln)
                    self.finalize(container, self.line_number)
            elif self.offset < len(ln) and not self.blank:
                container = self.add_child('paragraph', self.offset)
                self.advance_next_nonspace()
                self.add_line()
        self.last_line_length = len(ln)

    # -- continuation ------------------------------------------------------------
    def continue_block(self, container):
        t = container.type
        ln = self.line
        if t == 'paragraph':
            return 1 if self.blank else 0
        if t == 'list' or t == 'document':
            return 0
        if t == 'block_quote':
            if not self.indented and self.next_nonspace < len(ln) and \
                    ln[self.next_nonspace] == '>':
                self.advance_next_nonspace()
                self.advance_offset(1)
                if self.offset < len(ln) and ln[self.offset] in ' \t':
                    self.advance_offset(1, True)
                return 0
            return 1
        if t == 'item':
            ld = container.ldata
            if self.blank:
                if container.first_child is None:
                    return 1
                self.advance_next_nonspace()
            elif self.indent >= ld.marker_offset + ld.padding:
                self.advance_offset(ld.marker_offset + ld.padding, True)
            else:
                return 1
            return 0
        if t == 'code_block':
            if container.fenced:
                ns = self.next_nonspace
                if self.indent <= 3 and ns < len(ln) and ln[ns] == container.fence_char:
                    m = _CLOSE_FENCE.match(ln, ns)
                    if m and len(m.group(1)) >= container.fence_len and \
                            m.group(1)[0] == container.fence_char:
                        self.last_line_length = len(ln)
                        self.finalize(container, self.line_number)
                        return 2
                i = container.fence_offset
                while i > 0 and self.offset < len(ln) and ln[self.offset] in ' \t':
                    self.advance_offset(1, True)
                    i -= 1
                return 0
            if self.indent >= 4:
                self.advance_offset(4, True)
            elif self.blank:
                self.advance_next_nonspace()
            else:
                return 1
            return 0
        if t == 'html_block':
            return 1 if (self.blank and container.html_type in (6, 7)) else 0
        return 1  # heading, thematic_break

    # -- block starts ------------------------------------------------------------
    def start_block_quote(self, container):
        ln = self.line
        if not self.indented and ln[self.next_nonspace] == '>':
            self.advance_next_nonspace()
            self.advance_offset(1)
            if self.offset < len(ln) and ln[self.offset] in ' \t':
                self.advance_offset(1, True)
            self.close_unmatched()
            self.add_child('block_quote', self.next_nonspace)
            return 1
        return 0

    def start_atx(self, container):
        if self.indented:
            return 0
        ln = self.line
        if ln[self.next_nonspace] != '#':
            return 0
        m = _ATX.match(ln, self.next_nonspace)
        if not m:
            return 0
        self.advance_next_nonspace()
        self.advance_offset(m.end() - m.start())
        self.close_unmatched()
        node = self.add_child('heading', self.next_nonspace)
        node.level = len(m.group().strip())
        rest = ln[self.offset:]
        rest = rest.strip(' \t')
        # remove optional closing sequence
        if rest and rest[-1] == '#':
            stripped = rest.rstrip('#')
            if stripped == '':
                rest = ''
            elif stripped[-1] in ' \t':
                rest = stripped.rstrip(' \t')
        node.content = rest
        self.advance_offset(len(ln) - self.offset)
        return 2

    def start_fence(self, container):
        if self.indented:
            return 0
        ln = self.line
        ns = self.next_nonspace
        c = ln[ns]
        if c != '`' and c != '~':
            return 0
        j = ns
        while j < len(ln) and ln[j] == c:
            j += 1
        k = j - ns
        if k < 3:
            return 0
        if c == '`' and '`' in ln[j:]:
            return 0
        self.close_unmatched()
        node = self.add_child('code_block', ns)
        node.fenced = True
        node.fence_char = c
        node.fence_len = k
        node.fence_offset = self.indent
        self.advance_next_nonspace()
        self.advance_offset(k)
        return 2

    def start_html(self, container):
        if self.indented:
            return 0
        ln = self.line
        ns = self.next_nonspace
        if ln[ns] != '<':
            return 0
        for bt in range(1, 8):
            if HTML_OPEN[bt].match(ln, ns):
                if bt == 7:
                    if container.type == 'paragraph':
                        continue
                    if not self.all_closed and not self.blank and \
                            self.tip.type == 'paragraph':
                        continue
                    if _TYPE7_EXCL.match(ln, ns):
                        continue
                self.close_unmatched()
                node = self.add_child('html_block', ns)
                node.html_type = bt
                return 2
        return 0

    def start_setext(self, container):
        if self.indented or container.type != 'paragraph':
            return 0
        ln = self.line
        ns = self.next_nonspace
        c = ln[ns]
        if c != '=' and c != '-':
            return 0
        if not _SETEXT.match(ln, ns):
            return 0
        self.close_unmatched()
        content = ''.join(container.lines)
        pos = 0
        n = len(content)
        while pos < n and content[pos] == '[':
            p = parse_reference(content, pos, self.refmap)
            if p is None:
                break
            pos = p
        content = content[pos:]
        if content.strip(' \t\n') != '':
            heading = Node('heading')
            heading.sl, heading.sc = container.sl, container.sc
            heading.level = 1 if c == '=' else 2
            heading.content = content.strip(' \t\n')
            container.insert_after(heading)
            container.unlink()
            self.tip = heading
            self.advance_offset(len(ln) - self.offset)
            return 2
        container.lines = [content]
        return 0

    def start_hr(self, container):
        if self.indented:
            return 0
        ln = self.line
        ns = self.next_nonspace
        c = ln[ns]
        if c not in '*_-':
            return 0
        # Whole rest of line must be c / spaces / tabs.  The start of that
        # suffix is computed once per line and character, so that deeply
        # nested "- - - ..." lines stay linear.
        start = self._hr_suffix.get(c)
        if start is None:
            i = len(ln)
            while i > 0 and (ln[i - 1] == c or ln[i - 1] in ' \t'):
                i -= 1
            start = self._hr_suffix[c] = i
        if ns < start or ln.count(c, ns) < 3:
            return 0
        self.close_unmatched()
        self.add_child('thematic_break', ns)
        self.advance_offset(len(ln) - self.offset)
        return 2

    def parse_list_marker(self, container):
        if self.indent >= 4:
            return None
        ln = self.line
        ns = self.next_nonspace
        data = ListData()
        data.tight = True
        data.bullet = None
        data.start = 1
        data.delim = None
        m = _BULLET.match(ln, ns)
        if m:
            data.type = 'bullet'
            data.bullet = m.group()
            mlen = 1
        else:
            m = _ORDERED.match(ln, ns)
            if m and (container.type != 'paragraph' or m.group(1) == '1'):
                data.type = 'ordered'
                data.start = int(m.group(1))
                data.delim = m.group(2)
                mlen = m.end() - ns
            else:
                return None
        nxt = ns + mlen
        if nxt < len(ln) and ln[nxt] not in ' \t':
            return None
        if container.type == 'paragraph' and not _NONBLANK.search(ln, nxt):
            return None
        data.marker_offset = self.indent
        self.advance_next_nonspace()
        self.advance_offset(mlen, True)
        spaces_col = self.column
        spaces_off = self.offset
        while True:
            self.advance_offset(1, True)
            if not (self.column - spaces_col < 5 and self.offset < len(ln)
                    and ln[self.offset] in ' \t'):
                break
        blank_item = self.offset >= len(ln)
        after = self.column - spaces_col
        if after >= 5 or after < 1 or blank_item:
            data.padding = mlen + 1
            self.column = spaces_col
            self.offset = spaces_off
            self.partial_tab = False
            if self.offset < len(ln) and ln[self.offset] in ' \t':
                self.advance_offset(1, True)
        else:
            data.padding = mlen + after
        return data

    def start_list(self, container):
        if self.indented and container.type != 'list':
            return 0
        ln = self.line
        ns = self.next_nonspace
        if ns >= len(ln):
            return 0
        c = ln[ns]
        if not (c in '*+-' or '0' <= c <= '9'):
            return 0
        data = self.parse_list_marker(container)
        if data is None:
            return 0
        self.close_unmatched()
        tip = self.tip
        if tip.type != 'list' or not self.lists_match(tip.ldata, data):
            node = self.add_child('list', ns)
            node.ldata = data
        item = self.add_child('item', ns)
        item.ldata = data
        return 1

    @staticmethod
    def lists_match(a, b):
        return a.type == b.type and a.delim == b.delim and a.bullet == b.bullet

    def start_indented_code(self, container):
        if self.indented and self.tip.type != 'paragraph' and not self.blank:
            self.advance_offset(4, True)
            self.close_unmatched()
            self.add_child('code_block', self.offset)
            return 2
        return 0

    _starts = [start_block_quote, start_atx, start_fence, start_html,
               start_setext, start_hr, start_list, start_indented_code]

    # -- finalize --------------------------------------------------------------------
    def finalize(self, block, line_number):
        above = block.parent
        block.open = False
        block.el = line_number
        block.ec = self.last_line_length
        t = block.type
        if t == 'paragraph':
            content = ''.join(block.lines)
            pos = 0
            n = len(content)
            while pos < n and content[pos] == '[':
                p = parse_reference(content, pos, self.refmap)
                if p is None:
                    break
                pos = p
            content = content[pos:]
            if content.strip(' \t\n') == '':
                block.unlink()
            else:
                block.content = content.strip(' \t\n')
        elif t == 'code_block':
            lines = block.lines or []
            if block.fenced:
                block.info = unescape_string(lines[0].strip(' \t\n')) if lines else ''
                block.literal = ''.join(lines[1:])
            else:
                end = len(lines)
                while end > 0 and lines[end - 1].strip(' \t\n') == '':
                    end -= 1
                block.literal = ''.join(lines[:end])
                block.ec = block.ec  # unchanged
        elif t == 'html_block':
            block.literal = ''.join(block.lines or [])
        elif t == 'list':
            block.tight = True
            item = block.first_child
            while item is not None:
                if self.ends_with_blank_line(item) and item.next is not None:
                    block.tight = False
                    break
                sub = item.first_child
                while sub is not None:
                    if self.ends_with_blank_line(sub) and (item.next is not None or
                                                           sub.next is not None):
                        block.tight = False
                        break
                    sub = sub.next
                if not block.tight:
                    break
                item = item.next
        if (t == 'list' or t == 'item') and block.last_child is not None:
            block.el = block.last_child.el
            block.ec = block.last_child.ec
        self.tip = above

    @staticmethod
    def ends_with_blank_line(block):
        while block is not None:
            if block.last_line_blank:
                return True
            if not block.last_line_checked and block.type in ('list', 'item'):
                block.last_line_checked = True
                block = block.last_child
            else:
                block.last_line_checked = True
                break
        return False


def prepare_text(data):
    """Normalise raw input (bytes or str) into a str ready for parsing."""
    if isinstance(data, bytes):
        data = data.decode('utf-8', 'replace')
    if data.startswith('﻿'):
        data = data[1:]
    return data.replace('\x00', '�')


def parse(data, smart=False):
    return BlockParser(smart=smart).parse(prepare_text(data))
