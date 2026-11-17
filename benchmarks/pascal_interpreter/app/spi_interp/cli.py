import sys

from .errors import SpiError, SpiRuntimeError
from .interpreter import Interpreter
from .parser import parse
from .semantic import SemanticAnalyzer

USAGE = "usage: spi <file.pas> [--scope] [--stack]"


def run_source(text, scope=False, stack=False, out=print):
    """Lex/parse/analyze/interpret `text`. Raises SpiError subclasses."""
    try:
        tree = parse(text)
        SemanticAnalyzer(scope_log=out if scope else None).analyze(tree)
        Interpreter(tree, show_stack=stack, out=out).interpret()
    except RecursionError:
        raise SpiRuntimeError("Maximum recursion depth exceeded")
    except OverflowError:
        raise SpiRuntimeError("Numeric overflow")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    flags = {a for a in argv if a.startswith("--")}
    files = [a for a in argv if not a.startswith("--")]
    if len(files) != 1 or not flags <= {"--scope", "--stack"}:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        with open(files[0], encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"error: cannot read {files[0]}: {e.strerror}", file=sys.stderr)
        return 2
    try:
        run_source(text, "--scope" in flags, "--stack" in flags)
    except SpiError as e:
        print(e)
        return 1
    return 0
