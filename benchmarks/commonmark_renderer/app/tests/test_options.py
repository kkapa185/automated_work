"""R1, R5-R8, R10: CLI behaviour and options (expected values derived by hand
from the specification / documented cmark conventions)."""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CMARK = os.path.join(ROOT, 'cmark')


def run(args, data=b'', check=True):
    p = subprocess.run([sys.executable, CMARK] + args, input=data,
                       capture_output=True)
    if check:
        assert p.returncode == 0, p.stderr
    return p


def md(text, *args):
    return run(list(args), text.encode('utf-8')).stdout.decode('utf-8')


class CliTests(unittest.TestCase):
    def test_r1_stdin(self):
        self.assertEqual(md('# Hi\n'), '<h1>Hi</h1>\n')

    def test_r1_files_concatenated(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, 'a.md')
            b = os.path.join(d, 'b.md')
            with open(a, 'w') as f:
                f.write('one\n\n')
            with open(b, 'w') as f:
                f.write('two\n')
            out = run([a, b]).stdout.decode()
            self.assertEqual(out, '<p>one</p>\n<p>two</p>\n')

    def test_r1_missing_file(self):
        p = run(['/nonexistent/file.md'], check=False)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, b'')
        self.assertIn(b'nonexistent', p.stderr)

    def test_r1_to_html_and_other(self):
        self.assertEqual(md('a\n', '--to', 'html'), '<p>a</p>\n')
        self.assertEqual(run(['--to', 'bogus'], b'a', check=False).returncode, 1)

    def test_r1_unknown_option(self):
        self.assertEqual(run(['--frobnicate'], b'a', check=False).returncode, 1)

    def test_empty_input(self):
        self.assertEqual(md(''), '')

    def test_r10_line_endings_and_bad_bytes(self):
        out = run([], b'a\r\nb\rc\n\x00\xff\n').stdout.decode('utf-8')
        self.assertEqual(out, '<p>a\nb\nc\n��</p>\n')

    def test_r10_no_trailing_newline(self):
        self.assertEqual(md('a'), '<p>a</p>\n')


class SafetyTests(unittest.TestCase):
    def test_r6_raw_html_omitted(self):
        self.assertEqual(md('a <b>x</b>\n'),
                         '<p>a <!-- raw HTML omitted -->x<!-- raw HTML omitted --></p>\n')
        self.assertEqual(md('<div>\nx\n</div>\n'), '<!-- raw HTML omitted -->\n')

    def test_r6_unsafe_passthrough(self):
        self.assertEqual(md('a <b>x</b>\n', '--unsafe'), '<p>a <b>x</b></p>\n')
        self.assertEqual(md('<div>\nx\n</div>\n', '--unsafe'), '<div>\nx\n</div>\n')

    def test_r6_dangerous_urls(self):
        for url in ('javascript:alert(1)', 'JavaScript:x', 'vbscript:x',
                    'file:///etc/passwd', 'data:text/html;base64,AAAA'):
            self.assertEqual(md('[a](%s)\n' % url), '<p><a href="">a</a></p>\n', url)
            self.assertEqual(md('![a](%s)\n' % url), '<p><img src="" alt="a" /></p>\n', url)

    def test_r6_safe_data_images(self):
        for kind in ('png', 'gif', 'jpeg', 'webp'):
            self.assertEqual(md('![a](data:image/%s;base64,AA)\n' % kind),
                             '<p><img src="data:image/%s;base64,AA" alt="a" /></p>\n' % kind)

    def test_r6_unsafe_urls_kept(self):
        self.assertEqual(md('[a](javascript:x)\n', '--unsafe'),
                         '<p><a href="javascript:x">a</a></p>\n')

    def test_r6_https_ok(self):
        self.assertEqual(md('[a](https://x.y/z)\n'), '<p><a href="https://x.y/z">a</a></p>\n')


class BreakTests(unittest.TestCase):
    def test_r7_hardbreaks(self):
        self.assertEqual(md('a\nb\n', '--hardbreaks'), '<p>a<br />\nb</p>\n')

    def test_r7_nobreaks(self):
        self.assertEqual(md('a\nb\n', '--nobreaks'), '<p>a b</p>\n')

    def test_r7_default_softbreak(self):
        self.assertEqual(md('a\nb\n'), '<p>a\nb</p>\n')

    def test_r7_explicit_breaks_unaffected(self):
        self.assertEqual(md('a  \nb\n', '--nobreaks'), '<p>a<br />\nb</p>\n')


class SmartTests(unittest.TestCase):
    def check(self, src, expected):
        self.assertEqual(md(src + '\n', '--smart'), '<p>%s</p>\n' % expected)

    def test_double_quotes(self):
        self.check('"Hello," said the spider.', '“Hello,” said the spider.')

    def test_single_quotes(self):
        self.check("'Shelob' is my name.", '‘Shelob’ is my name.')

    def test_apostrophe(self):
        self.check("Were you alive in the 70's?", 'Were you alive in the 70’s?')

    def test_nested_quotes(self):
        self.check('\'He said, "I want to go."\'',
                   '‘He said, “I want to go.”’')

    def test_dashes(self):
        self.check('a -- b --- c', 'a – b — c')
        self.check('a---- b', 'a–– b')      # 4 -> two en dashes
        self.check('a------ b', 'a—— b')    # 6 -> two em dashes
        self.check('a----- b', 'a—– b')     # 5 -> em + en
        self.check('a - b', 'a - b')

    def test_ellipsis(self):
        self.check('wait...', 'wait…')
        self.check('a..b', 'a..b')

    def test_code_untouched(self):
        self.check('`"a" -- b...`', '<code>&quot;a&quot; -- b...</code>')

    def test_off_by_default(self):
        self.assertEqual(md('"a" -- b...\n'), '<p>&quot;a&quot; -- b...</p>\n')


class SourcePosTests(unittest.TestCase):
    def test_r8_blocks(self):
        out = md('> a\n\n# h\n\n---\n', '--sourcepos')
        self.assertEqual(out, (
            '<blockquote data-sourcepos="1:1-1:3">\n'
            '<p data-sourcepos="1:3-1:3">a</p>\n</blockquote>\n'
            '<h1 data-sourcepos="3:1-3:3">h</h1>\n'
            '<hr data-sourcepos="5:1-5:3" />\n'))

    def test_r8_tight_list(self):
        out = md('- a\n- b\n', '--sourcepos')
        self.assertEqual(out, (
            '<ul data-sourcepos="1:1-2:3">\n'
            '<li data-sourcepos="1:1-1:3">a</li>\n'
            '<li data-sourcepos="2:1-2:3">b</li>\n</ul>\n'))

    def test_r8_fenced_and_paragraph(self):
        out = md('```\nx\n```\n\nab\ncd\n', '--sourcepos')
        self.assertEqual(out, (
            '<pre data-sourcepos="1:1-3:3"><code>x\n</code></pre>\n'
            '<p data-sourcepos="5:1-6:2">ab\ncd</p>\n'))

    def test_r8_ordered_start(self):
        out = md('3. a\n', '--sourcepos')
        self.assertTrue(out.startswith('<ol start="3" data-sourcepos="1:1-1:4">'), out)

    def test_r8_off_by_default(self):
        self.assertNotIn('sourcepos', md('> a\n'))


class FormatTests(unittest.TestCase):
    def test_r5_url_encoding(self):
        self.assertEqual(md('[a](/a b "t")\n'), '<p>[a](/a b &quot;t&quot;)</p>\n')
        self.assertEqual(md('[a](</a b>)\n'), '<p><a href="/a%20b">a</a></p>\n')
        self.assertEqual(md('[a](/é?x=1&y=2\'`)\n'),
                         '<p><a href="/%C3%A9?x=1&amp;y=2&#x27;%60">a</a></p>\n')
        self.assertEqual(md('[a](/%41%zz)\n'), '<p><a href="/%41%zz">a</a></p>\n')

    def test_r5_attribute_escaping(self):
        self.assertEqual(md('[a](/u "x<y>&\\"z")\n'),
                         '<p><a href="/u" title="x&lt;y&gt;&amp;&quot;z">a</a></p>\n')
        self.assertEqual(md('```a"<b c\nx\n```\n'),
                         '<pre><code class="language-a&quot;&lt;b">x\n</code></pre>\n')

    def test_r5_image_alt_plain(self):
        self.assertEqual(md('![a *b* `c` ![d](/e)\nf](/g "t")\n'),
                         '<p><img src="/g" alt="a b c d f" title="t" /></p>\n')

    def test_r5_tight_loose(self):
        self.assertEqual(md('- a\n- b\n'), '<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n')
        self.assertEqual(md('- a\n\n- b\n'),
                         '<ul>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n</ul>\n')
        self.assertEqual(md('- a\n  - b\n'),
                         '<ul>\n<li>a\n<ul>\n<li>b</li>\n</ul>\n</li>\n</ul>\n')

    def test_r5_ordered_start(self):
        self.assertEqual(md('1. a\n'), '<ol>\n<li>a</li>\n</ol>\n')
        self.assertEqual(md('0. a\n'), '<ol start="0">\n<li>a</li>\n</ol>\n')

    def test_r4_entities(self):
        self.assertEqual(md('&amp; &#35; &#X22; &#0; &copy; &nosuch; &ngE;\n'),
                         '<p>&amp; # &quot; � © &amp;nosuch; ≧̸</p>\n')

    def test_r4_empty_input_edge_cases(self):
        self.assertEqual(md('\n\n\n'), '')
        self.assertEqual(md('   \n'), '')

    def test_r4_label_casefold(self):
        self.assertEqual(md('[ẞ]\n\n[SS]: /url\n'),
                         '<p><a href="/url">ẞ</a></p>\n')

    def test_r3_html_block_ends(self):
        self.assertEqual(md('<!-- a\n\nb -->\n', '--unsafe'), '<!-- a\n\nb -->\n')
        self.assertEqual(md('<div>\n\nb\n', '--unsafe'), '<div>\n<p>b</p>\n')


if __name__ == '__main__':
    unittest.main()
