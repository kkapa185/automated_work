"""R9: adversarial inputs must render quickly (and without crashing)."""
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cmarklib import markdown_to_html  # noqa: E402

LIMIT = float(os.environ.get('CMARK_PERF_LIMIT', '5'))
N = 100000

CASES = {
    'nested_brackets_open': '[' * N,
    'nested_brackets_pairs': '[' * (N // 2) + 'a' + ']' * (N // 2),
    'brackets_then_parens': '[a](b' * (N // 5),
    'image_openers': '![' * (N // 2),
    'images_then_links': '![' * (N // 4) + '[a](b)' * (N // 12),
    'link_openers_then_matches': '[' * (N // 2) + ']( )' * (N // 8),
    'shortcut_refs': '[a]\n\n[a]: /u\n\n' + '[a][a] ' * (N // 7),
    'emph_openers': '*a ' * (N // 2),
    'emph_alternating': '*a **b ' * (N // 7) + '_c__' * (N // 7),
    'emph_closers': 'a* ' * (N // 2),
    'emph_nested': '*' * (N // 2) + 'a' + '*' * (N // 2),
    'underscore_mix': '_a*' * (N // 3),
    'emph_rule_of_3': '*a**' * (N // 4),
    'blockquote_deep': '> ' * N,
    'blockquote_gt_only': '>' * N,
    'blockquote_lines': ''.join('>' * k + ' x\n' for k in range(1, 400)),
    'list_deep': '- ' * N,
    'ordered_list_deep': '1. ' * (N // 2),
    'list_items_many': '- a\n' * N,
    'many_refdefs': ''.join('[a%d]: /url%d "t"\n' % (i, i) for i in range(N // 12)) + '[a5]',
    'refdefs_unterminated': '[a]: /u\n"t\n' * (N // 8),
    'refdef_labels_long': '[' + 'a' * N + ']: /x\n',
    'backticks_run': '`' * N,
    'backticks_mixed': ''.join('`' * (i % 50 + 1) + 'a ' for i in range(N // 20)),
    'backticks_unmatched': '`a ' * (N // 3),
    'backtick_ladder': ''.join('`' * k + ' ' for k in range(1, 400)),
    'lt_runs': '<' * N,
    'lt_a_runs': '<a ' * (N // 3),
    'html_comment_open': '<!--' * (N // 4),
    'html_pi_open': '<?a ' * (N // 4),
    'html_decl_open': '<!A ' * (N // 4),
    'html_cdata_open': '<![CDATA[' * (N // 9),
    'html_attr_quotes': '<a b="' * (N // 6),
    'bang_runs': '!' * N,
    'ampersands': '&' * N + '&#' * (N // 2),
    'backslashes': '\\' * N,
    'long_line': 'word ' * (N // 2),
    'many_hard_breaks': 'a  \n' * (N // 4),
    'setext_lines': 'a\n' * (N // 2) + '===\n',
    'hr_lines': '* * *\n' * (N // 6),
    'fenced_many': '```\n' * (N // 4),
    'indented_code': '    code\n' * (N // 9),
    'html_block_lines': '<div>\n' * (N // 6),
    'link_dest_parens': '[a](' + '(' * N,
    'link_title_open': '[a](b "' * (N // 7),
    'autolink_like': '<a:' * (N // 3) + '<a@' * (N // 3),
    'smart_quotes': '"a\' ' * (N // 4),
    'tabs': '\t- a\n\t\t\tb\n' * (N // 12),
    'deep_list_indented_lines': '- ' * 5000 + 'x\n' + ('  ' * 5000 + 'y\n') * 20,
    'deep_quote_lines': '> ' * 5000 + 'x\n' + ('> ' * 5000 + 'y\n') * 20,
    'deep_quote_blank_lines': '> ' * 20000 + 'x\n' + '\n' * 20000,
    'hr_in_nested_list': '- ' * N + 'x',
    'table_of_stuff': '# h\n\n- a\n  - b\n    > c\n\n```\nx\n```\n\n' * (N // 40),
}


class PerfTests(unittest.TestCase):
    pass


def _make(name, text, smart):
    def test(self):
        t0 = time.time()
        out = markdown_to_html(text, smart=smart, unsafe=True)
        dt = time.time() - t0
        self.assertIsInstance(out, str)
        self.assertLess(dt, LIMIT, '%s took %.2fs' % (name, dt))
    return test


for _name, _text in CASES.items():
    setattr(PerfTests, 'test_perf_' + _name, _make(_name, _text, False))
setattr(PerfTests, 'test_perf_smart_quotes_smart', _make('sq', CASES['smart_quotes'], True))
setattr(PerfTests, 'test_perf_dashes_smart', _make('d', '-' * N + '...' * N, True))

if __name__ == '__main__':
    unittest.main()
