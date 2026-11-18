"""AST node shared by blocks and inlines (doubly linked sibling lists)."""


class Node:
    __slots__ = ('type', 'parent', 'first_child', 'last_child', 'prev', 'next',
                 'literal', 'dest', 'title', 'level', 'info', 'tight', 'open',
                 'lines', 'sl', 'sc', 'el', 'ec', 'last_line_blank',
                 'last_line_checked', 'html_type', 'fence_char', 'fence_len',
                 'fence_offset', 'fenced', 'ldata', 'content')

    def __init__(self, type_, literal=None):
        self.type = type_
        self.parent = self.first_child = self.last_child = None
        self.prev = self.next = None
        self.literal = literal
        self.dest = self.title = self.info = None
        self.level = 0
        self.tight = True
        self.open = True
        self.lines = None
        self.sl = self.sc = self.el = self.ec = 0
        self.last_line_blank = False
        self.last_line_checked = False
        self.html_type = 0
        self.fence_char = None
        self.fence_len = 0
        self.fence_offset = 0
        self.fenced = False
        self.ldata = None
        self.content = None

    def append_child(self, child):
        child.parent = self
        last = self.last_child
        if last is not None:
            last.next = child
            child.prev = last
        else:
            self.first_child = child
            child.prev = None
        child.next = None
        self.last_child = child

    def unlink(self):
        p = self.parent
        if self.prev is not None:
            self.prev.next = self.next
        elif p is not None:
            p.first_child = self.next
        if self.next is not None:
            self.next.prev = self.prev
        elif p is not None:
            p.last_child = self.prev
        self.parent = self.prev = self.next = None

    def insert_after(self, sibling):
        sibling.unlink()
        sibling.parent = self.parent
        sibling.prev = self
        sibling.next = self.next
        if self.next is not None:
            self.next.prev = sibling
        elif self.parent is not None:
            self.parent.last_child = sibling
        self.next = sibling
