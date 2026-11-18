"""Smoke check: run the real shell on a fixture and verify its output."""
import os
import subprocess
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, 'tests', 'fixtures', 'smoke.sql'), 'rb') as f:
    p = subprocess.run([sys.executable, os.path.join(root, 'sqldb')], stdin=f, stdout=subprocess.PIPE)
expected = b'1|x|1.0\n2|y|2.0\n'
if p.returncode != 0 or p.stdout != expected:
    sys.stderr.write('smoke failed: %r\n' % p.stdout)
    sys.exit(1)
