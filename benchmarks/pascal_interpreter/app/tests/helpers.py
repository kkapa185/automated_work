import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from spi_interp.cli import run_source  # noqa: E402


def run(text, **kw):
    """Run source through the whole pipeline, returning captured stdout."""
    buf = []
    run_source(text, out=buf.append, **kw)
    return "".join(s + "\n" for s in buf)


def cli(text, *flags):
    with tempfile.NamedTemporaryFile('w', suffix='.pas', delete=False) as f:
        f.write(text)
    try:
        p = subprocess.run([os.path.join(ROOT, 'spi'), f.name, *flags],
                           capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    return p


def line(name, value):
    return "   " + name.ljust(20) + ": " + str(value) + "\n"
