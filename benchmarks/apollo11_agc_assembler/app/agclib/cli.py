"""Command line interface: ``agcasm assemble MAIN.agc -o out.binsource``."""

from __future__ import annotations

import argparse
import os
import sys

from .assembler import Assembler
from .output import listing_text, rope_text, summary_text, symbols_json


def _write(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def build_parser():
    p = argparse.ArgumentParser(prog="agcasm", description="Block II AGC assembler")
    sub = p.add_subparsers(dest="cmd")
    a = sub.add_parser("assemble", help="assemble a program into a core rope image")
    a.add_argument("source", help="top-level source file (MAIN.agc)")
    a.add_argument("-o", "--output", required=True, help="rope image (.binsource) to write")
    a.add_argument("--symbols", help="write the symbol table as JSON")
    a.add_argument("--listing", help="write an assembly listing")
    a.add_argument("-q", "--quiet", action="store_true", help="do not print the bank summary")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd != "assemble":
        parser.print_usage(sys.stderr)
        print("agcasm: error: a command is required (try 'assemble')", file=sys.stderr)
        return 2
    asm = Assembler()
    try:
        ok = asm.assemble_file(args.source)
    except RecursionError:
        print(f"{args.source}:1: include nesting too deep", file=sys.stderr)
        return 1
    for ctx, msg in asm.warnings:
        where = f"{ctx.file}:{ctx.lineno}: " if ctx is not None else ""
        print(f"{where}warning: {msg}", file=sys.stderr)
    for d in asm.diags:
        print(str(d), file=sys.stderr)
    if not ok:
        print(f"agcasm: {len(asm.diags)} error(s); no output written", file=sys.stderr)
        return 1
    try:
        _write(args.output, rope_text(asm, os.path.basename(args.source)))
        if args.symbols:
            _write(args.symbols, symbols_json(asm))
        if args.listing:
            _write(args.listing, listing_text(asm))
    except OSError as exc:
        print(f"agcasm: cannot write output: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        sys.stdout.write(summary_text(asm))
    return 0


if __name__ == "__main__":
    sys.exit(main())
