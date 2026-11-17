"""Source-line tokenizer and include expansion.

A source line is free-form but column sensitive in one respect: a label must
start in column 1; any line starting with white space has no label.  The
remaining fields are the operation (or, in interpretive code, an operand), the
operand text and an optional ``#`` comment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import re

from .model import AsmError
from .tables import is_known_mnemonic

_MARKER = re.compile(r"^[+-]\d+D?$")


@dataclass
class Line:
    file: str
    lineno: int
    text: str
    label: str | None = None
    fields: list = field(default_factory=list)   # whitespace separated tokens of the code part
    kind: str = "code"                           # 'code', 'blank', 'comment'

    @property
    def op(self):
        return self.fields[0] if self.fields else None

    @property
    def operand(self):
        return " ".join(self.fields[1:])


def _split_columns(code):
    """Split a code field into tokens, dropping annotations in the far right columns.

    The original card format ended the operand field well before column 41; the
    transcriptions keep stray scale/stack annotations beyond it (for example
    ``DLOAD SL2   B2``).  Tokens after the operation that start at or beyond
    column 41 (tabs every 8) are annotations, not operands.
    """
    ex = code.expandtabs(8)
    toks = []
    for m in re.finditer(r"\S+", ex):
        toks.append((m.start(), m.group()))
    if not toks:
        return []
    first_is_label = bool(code) and code[0] not in " \t"
    keep_to = 2 if first_is_label else 1
    out = []
    for i, (col, tok) in enumerate(toks):
        if i >= keep_to and col >= 48:
            break
        out.append(tok)
    return out


def parse_line(text, file="<string>", lineno=1):
    """Split one physical source line into label and fields."""
    raw = text.rstrip("\r\n").replace("\f", " ")
    ln = Line(file, lineno, raw)
    if not raw.strip():
        ln.kind = "blank"
        return ln
    if raw.startswith("#"):
        ln.kind = "comment"
        return ln
    code = raw.split("#", 1)[0]
    toks = _split_columns(code)
    if not toks:
        ln.kind = "comment"
        return ln
    if raw[0] not in " \t":
        ln.label = toks[0]
        toks = toks[1:]
    # '+n' / '-n' in the label field (or just before an operation) is only a
    # relative-location marker, not a symbol definition
    if ln.label is not None and _MARKER.match(ln.label):
        ln.label = None
    if toks and _MARKER.match(toks[0]) and len(toks) > 1 and is_known_mnemonic(toks[1]):
        toks = toks[1:]
    ln.fields = toks
    return ln


def include_name(text):
    """If ``text`` is an include line ('$FILE.agc ...') return the file name."""
    if text.startswith("$"):
        parts = text[1:].split()
        if parts:
            return parts[0]
        raise AsmError("empty include directive")
    return None


def _edit1(a, b):
    if a == b:
        return False
    if len(a) < len(b):
        a, b = b, a
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) - len(b) != 1:
        return False
    i = 0
    while i < len(b) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i:]


def _find_similar(base, name):
    """A unique file in ``base`` that is a near miss of the include ``name``.

    The transcribed MAIN files contain a couple of mistyped or abbreviated
    include names (e.g. a missing 'GENERAL_' prefix); a unique file whose name
    ends with the requested one, or differs by one character, is used.
    """
    try:
        names = os.listdir(base or ".")
    except OSError:
        return None
    cands = [n for n in names if n != name and (n.endswith("_" + name) or _edit1(n, name))]
    return cands[0] if len(cands) == 1 else None


def read_source(path, diags=None, _stack=None, warns=None):
    """Read ``path`` and recursively expand ``$FILE`` includes.

    Returns a list of :class:`Line` objects in listing order.  Missing include
    files and include cycles are reported through ``diags`` (a list of
    :class:`AsmError`) when given, else raised.
    """
    stack = _stack or []
    real = os.path.abspath(path)
    out = []

    def problem(err):
        if diags is None:
            raise err
        diags.append(err)

    if real in stack:
        problem(AsmError(f"include cycle: {path}"))
        return out
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except OSError as exc:
        problem(AsmError(f"cannot read '{path}': {exc.strerror or exc}"))
        return out
    if lines and lines[-1] == "":
        lines.pop()
    base = os.path.dirname(path)
    for i, text in enumerate(lines, 1):
        try:
            inc = include_name(text)
        except AsmError as exc:
            exc.file, exc.line = path, i
            problem(exc)
            continue
        if inc is not None:
            ln = Line(path, i, text.rstrip("\r"), kind="include")
            out.append(ln)
            target = os.path.join(base, inc)
            if not os.path.exists(target):
                alt = _find_similar(base, inc)
                if alt is not None:
                    if warns is not None:
                        warns.append((ln, f"include '{inc}' not found; using '{alt}'"))
                    target = os.path.join(base, alt)
            try:
                sub = read_source(target, diags, stack + [real], warns)
            except AsmError as exc:
                exc.file, exc.line = path, i
                raise
            if diags is not None:
                # attribute missing-file diagnostics to the including line
                for d in diags:
                    if d.file is None:
                        d.file, d.line = path, i
            out.extend(sub)
        else:
            out.append(parse_line(text, path, i))
    return out
