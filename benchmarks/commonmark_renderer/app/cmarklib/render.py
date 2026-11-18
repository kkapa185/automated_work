"""Iterative HTML renderer producing cmark-style output."""
from .util import escape_href, escape_html, is_dangerous_url

_CONTAINERS = frozenset(['document', 'block_quote', 'list', 'item', 'heading',
                         'paragraph', 'emph', 'strong', 'link', 'image'])


def render_html(doc, unsafe=False, hardbreaks=False, nobreaks=False,
                sourcepos=False):
    out = []
    state = {'last': '\n'}

    def put(s):
        if s:
            out.append(s)
            state['last'] = s[-1]

    def cr():
        if state['last'] != '\n':
            out.append('\n')
            state['last'] = '\n'

    def sp(node):
        if sourcepos:
            return ' data-sourcepos="%d:%d-%d:%d"' % (node.sl, node.sc, node.el, node.ec)
        return ''

    plain = None  # image node whose children are rendered as alt text
    node = doc
    entering = True
    while True:
        t = node.type
        if plain is not None:
            if node is plain and not entering:
                plain = None
                put('"')
                if node.title:
                    put(' title="' + escape_html(node.title) + '"')
                put(' />')
            elif entering:
                if t in ('text', 'code', 'html_inline'):
                    put(escape_html(node.literal))
                elif t in ('softbreak', 'linebreak'):
                    put(' ')
        else:
            if entering:
                _enter(node, t, put, cr, sp, unsafe, hardbreaks, nobreaks)
                if t == 'image':
                    plain = node
            else:
                _exit(node, t, put, cr)
        # advance
        if entering and t in _CONTAINERS and node.first_child is not None:
            node = node.first_child
            continue
        if entering and t in _CONTAINERS:
            entering = False
            continue
        if not entering or t not in _CONTAINERS:
            if node is doc:
                break
            if node.next is not None:
                node = node.next
                entering = True
            else:
                node = node.parent
                entering = False
    return ''.join(out)


def _is_tight_paragraph(node):
    p = node.parent
    if p is not None and p.type == 'item':
        g = p.parent
        return g is not None and g.type == 'list' and g.tight
    return False


def _enter(node, t, put, cr, sp, unsafe, hardbreaks, nobreaks):
    if t == 'text':
        put(escape_html(node.literal))
    elif t == 'softbreak':
        if hardbreaks:
            put('<br />\n')
        elif nobreaks:
            put(' ')
        else:
            put('\n')
    elif t == 'linebreak':
        put('<br />\n')
    elif t == 'code':
        put('<code>' + escape_html(node.literal) + '</code>')
    elif t == 'html_inline':
        put(node.literal if unsafe else '<!-- raw HTML omitted -->')
    elif t == 'emph':
        put('<em>')
    elif t == 'strong':
        put('<strong>')
    elif t == 'link':
        s = '<a href="'
        if unsafe or not is_dangerous_url(node.dest):
            s += escape_href(node.dest)
        s += '"'
        if node.title:
            s += ' title="' + escape_html(node.title) + '"'
        put(s + '>')
    elif t == 'image':
        s = '<img src="'
        if unsafe or not is_dangerous_url(node.dest):
            s += escape_href(node.dest)
        put(s + '" alt="')
    elif t == 'paragraph':
        if not _is_tight_paragraph(node):
            cr()
            put('<p' + sp(node) + '>')
    elif t == 'heading':
        cr()
        put('<h%d%s>' % (node.level, sp(node)))
    elif t == 'block_quote':
        cr()
        put('<blockquote' + sp(node) + '>\n')
    elif t == 'list':
        cr()
        ld = node.ldata
        if ld.type == 'bullet':
            put('<ul' + sp(node) + '>\n')
        elif ld.start == 1:
            put('<ol' + sp(node) + '>\n')
        else:
            put('<ol start="%d"%s>\n' % (ld.start, sp(node)))
    elif t == 'item':
        cr()
        put('<li' + sp(node) + '>')
    elif t == 'code_block':
        cr()
        info = node.info if node.fenced else ''
        s = '<pre' + sp(node) + '><code'
        if info:
            word = info.split(None, 1)[0] if info.strip() else ''
            # first word ends at first space / tab
            i = 0
            while i < len(info) and info[i] not in ' \t\n\r\f\v':
                i += 1
            word = info[:i]
            if word:
                s += ' class="language-' + escape_html(word) + '"'
        put(s + '>' + escape_html(node.literal) + '</code></pre>\n')
    elif t == 'html_block':
        cr()
        put(node.literal if unsafe else '<!-- raw HTML omitted -->')
        cr()
    elif t == 'thematic_break':
        cr()
        put('<hr' + sp(node) + ' />\n')


def _exit(node, t, put, cr):
    if t == 'emph':
        put('</em>')
    elif t == 'strong':
        put('</strong>')
    elif t == 'link':
        put('</a>')
    elif t == 'paragraph':
        if not _is_tight_paragraph(node):
            put('</p>\n')
    elif t == 'heading':
        put('</h%d>\n' % node.level)
    elif t == 'block_quote':
        cr()
        put('</blockquote>\n')
    elif t == 'list':
        cr()
        put('</ul>\n' if node.ldata.type == 'bullet' else '</ol>\n')
    elif t == 'item':
        put('</li>\n')
