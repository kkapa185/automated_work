"""Command line entry point."""
import sys

from .lexer import Lexer, LexerError
from .parser import Parser, ParserError
from .semantic import SemanticAnalyzer, SemanticError
from .interpreter import Interpreter, InterpreterError


def run_source(text, scope=False, stack=False, out=print):
    tree = Parser(Lexer(text)).parse()
    SemanticAnalyzer(out if scope else None).analyze(tree)
    Interpreter(tree, stack, out).interpret()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    flags = {a for a in argv if a.startswith('--')}
    files = [a for a in argv if not a.startswith('--')]
    if flags - {'--scope', '--stack'} or len(files) != 1:
        print("usage: spi <file.pas> [--scope] [--stack]", file=sys.stderr)
        return 2
    try:
        with open(files[0], encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"spi: cannot read {files[0]}: {e}", file=sys.stderr)
        return 2
    try:
        run_source(text, '--scope' in flags, '--stack' in flags)
    except (LexerError, ParserError, SemanticError, InterpreterError) as e:
        print(e)
        return 1
    return 0
