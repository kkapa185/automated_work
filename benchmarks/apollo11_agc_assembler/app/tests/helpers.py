import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agclib.assembler import Assembler  # noqa: E402


def assemble(text, expect_ok=True):
    """Assemble a source snippet; returns the Assembler."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "MAIN.agc")
        with open(path, "w") as fh:
            fh.write(text)
        asm = Assembler()
        ok = asm.assemble_file(path)
    if expect_ok:
        assert ok, [str(e) for e in asm.diags]
    return asm


def words(asm, bank, n=1, start=0):
    return asm.fixed[bank][start:start + n]


def body(*lines, bank=4):
    """Wrap tab-separated source lines in a bank selection."""
    return f"\t\tBANK\t{bank:o}\n" + "\n".join(lines) + "\n"
