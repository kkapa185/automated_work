import io
import os
import subprocess
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from spi_interp.cli import run_source  # noqa: E402


def run(src, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        run_source(src, **kw)
    return buf.getvalue()


def prog(body, decls=""):
    return f"PROGRAM Main;\n{decls}\nBEGIN\n{body}\nEND.\n"
