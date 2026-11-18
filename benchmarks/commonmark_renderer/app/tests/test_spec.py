"""R2-R6, R10: run every example of docs/spec.txt through the renderer."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cmarklib import markdown_to_html  # noqa: E402

SPEC = os.path.join(ROOT, 'docs', 'spec.txt')


def load_examples():
    text = open(SPEC, encoding='utf-8').read().replace('\r\n', '\n')
    examples = []
    section = ''
    state = 0
    md = []
    html = []
    number = 0
    for ln in text.split('\n'):
        if state == 0:
            m = re.match(r'#{1,6} +(.*)', ln)
            if m and not ln.startswith('```'):
                section = m.group(1)
            if ln.startswith('```````````````````````````````` example'):
                state = 1
                md, html = [], []
        elif state == 1:
            if ln == '.':
                state = 2
            else:
                md.append(ln)
        else:
            if ln == '````````````````````````````````':
                number += 1
                examples.append((number, section,
                                 '\n'.join(md).replace('→', '\t') + '\n' if md else '',
                                 '\n'.join(html).replace('→', '\t') + '\n' if html else ''))
                state = 0
            else:
                html.append(ln)
    return examples


EXAMPLES = load_examples()


class SpecTests(unittest.TestCase):
    def test_example_count(self):
        self.assertGreaterEqual(len(EXAMPLES), 650)


def _make(num, section, md, html):
    def test(self):
        self.assertEqual(markdown_to_html(md, unsafe=True), html,
                         'example %d (%s)\n%r' % (num, section, md))
    return test


for _n, _s, _m, _h in EXAMPLES:
    setattr(SpecTests, 'test_example_%03d' % _n, _make(_n, _s, _m, _h))

if __name__ == '__main__':
    unittest.main()
