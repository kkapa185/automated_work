import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLDB = os.path.join(ROOT, 'sqldb')


def run(script, *args):
    """Run the shell on a script; returns (stdout, stderr, returncode)."""
    p = subprocess.run([sys.executable, SQLDB] + list(args), input=script.encode('utf-8'),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
    return p.stdout.decode('utf-8'), p.stderr.decode('utf-8'), p.returncode


def out(script, *args):
    return run(script, *args)[0]
