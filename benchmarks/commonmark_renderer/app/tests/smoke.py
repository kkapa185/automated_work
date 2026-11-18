"""Smoke test: run the real CLI on a sample document."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = subprocess.run([sys.executable, os.path.join(ROOT, 'cmark'), '--smart'],
                   input=b'# Title\n\n*hello* "world" -- [x](/y)\n',
                   capture_output=True)
expected = '<h1>Title</h1>\n<p><em>hello</em> \u201cworld\u201d \u2013 <a href="/y">x</a></p>\n'
assert p.returncode == 0, p.stderr
assert p.stdout.decode() == expected, p.stdout
print('smoke ok')
