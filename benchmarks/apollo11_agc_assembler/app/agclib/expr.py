"""Operand expression evaluation."""

from __future__ import annotations

import re

from .model import AsmError, Undefined, Val
from .numbers import parse_int

_INDEX_RE = re.compile(r"^(.*?)\s*,\s*([12])\s*$")


def split_index(text):
    """Split a trailing ',1' / ',2' index suffix.  Returns (expression, index or None)."""
    m = _INDEX_RE.match(text)
    if m:
        return m.group(1), int(m.group(2))
    return text, None


def _atom(tok, symbols, loc, relative, first):
    """Evaluate one term (no embedded spaces)."""
    if tok in symbols:
        return symbols[tok]
    n = parse_int(tok)
    if n is not None:
        if first and relative and tok[0] in "+-" and loc is not None:
            return loc + n
        return Val.num(n)
    # symbol followed immediately by a signed number: NAME+3, NAME-1
    for i in range(len(tok) - 1, 0, -1):
        if tok[i] in "+-" and tok[:i] in symbols:
            k = parse_int(tok[i:])
            if k is not None:
                return symbols[tok[:i]] + k
    raise Undefined(tok)


def evaluate(text, symbols, loc=None, relative=True):
    """Evaluate an address-field expression.

    ``symbols`` maps names to :class:`Val`.  ``loc`` is the location of the
    word being assembled; a leading signed number is relative to it when
    ``relative`` is true (``TC +2`` means "two locations ahead").
    """
    toks = text.split()
    if not toks:
        raise AsmError("missing operand")
    val = _atom(toks[0], symbols, loc, relative, True)
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in ("+", "-"):
            if i + 1 >= len(toks):
                raise AsmError(f"incomplete expression '{text}'")
            sign, body = t, toks[i + 1]
            i += 2
        elif t[0] in "+-":
            sign, body = t[0], t[1:]
            i += 1
        else:
            raise AsmError(f"bad expression '{text}'")
        n = parse_int(body)
        term = Val.num(n) if n is not None else _atom(body, symbols, loc, False, False)
        val = val + term if sign == "+" else val - term
    return val
