"""Numeric literal parsing and DEC/2DEC conversion."""

from __future__ import annotations

import re
from fractions import Fraction

from .model import AsmError, comp15

_OCT_RE = re.compile(r"^([+-]?)([0-7]+)$")
_DIGITS_RE = re.compile(r"^([+-]?)([0-9]+)$")
_DECD_RE = re.compile(r"^([+-]?)([0-9]+)D$")


def parse_int(tok):
    """Parse an address-field integer: octal by default, decimal with a trailing 'D'.

    Returns None if ``tok`` is not a numeric literal.
    """
    m = _OCT_RE.match(tok)
    if m:
        v = int(m.group(2), 8)
        return -v if m.group(1) == "-" else v
    m = _DECD_RE.match(tok)
    if m:
        v = int(m.group(2), 10)
        return -v if m.group(1) == "-" else v
    m = _DIGITS_RE.match(tok)
    if m:        # digits 8 or 9 cannot be octal: read as decimal
        v = int(m.group(2), 10)
        return -v if m.group(1) == "-" else v
    return None


_DEC_RE = re.compile(
    r"^(?P<sign>[+-]?)(?P<mant>\d*\.?\d*)(?:E(?P<exp>[+-]?\d+))?(?:(?:B)?(?P<bin>[+-]\d+)|B(?P<bin2>\d+))?\*?$"
)


def parse_decimal(text):
    """Parse a DEC operand into (negative, Fraction magnitude, binary scale)."""
    s = "".join(text.split()).upper()
    m = _DEC_RE.match(s)
    if not m or m.group("mant") == ".":
        raise AsmError(f"bad decimal constant '{text}'")
    mant = m.group("mant") or ("1" if m.group("exp") is not None else "")
    if not mant:
        raise AsmError(f"bad decimal constant '{text}'")
    b = m.group("bin") if m.group("bin") is not None else m.group("bin2")
    bscale = int(b) if b is not None else 0
    exp = int(m.group("exp")) if m.group("exp") is not None else 0
    if abs(bscale) > 200 or abs(exp) > 100 or len(mant) > 40:
        raise AsmError(f"decimal constant '{text}' out of range")
    value = Fraction(mant)
    if exp:
        value *= Fraction(10) ** exp
    return m.group("sign") == "-", value, bscale


def _round_half_up(fr):
    n = fr.numerator
    d = fr.denominator
    return (2 * n + d) // (2 * d)


def dec_to_int(text, bits):
    """Convert a DEC/2DEC operand to a (negative flag, magnitude) pair.

    The value is multiplied by ``2**B`` for a binary scale ``Bn``.  A result
    smaller than one is a fraction and is then scaled to fill the word
    (``2**bits``); a result of one or more is an integer and is used as is.
    """
    neg, value, bscale = parse_decimal(text)
    v = value * (Fraction(2) ** bscale)
    scaled = v * (1 << bits) if v < 1 else v
    mag = _round_half_up(scaled)
    if mag == (1 << bits) and v < 1:
        mag -= 1       # rounds up to full scale: saturate at the largest magnitude
    if mag >= (1 << bits):
        raise AsmError(f"decimal constant '{text}' out of range")
    return neg, mag


def dec_sp(text):
    neg, mag = dec_to_int(text, 14)
    return comp15(mag) if neg else mag


def dec_dp(text):
    neg, mag = dec_to_int(text, 28)
    hi, lo = mag >> 14, mag & 0o37777
    if neg:
        return comp15(hi), comp15(lo)
    return hi, lo


def parse_octal_word(tok):
    """OCT operand: up to 5 octal digits, optionally signed (negative = complement)."""
    m = _OCT_RE.match(tok)
    if not m:
        raise AsmError(f"bad octal constant '{tok}'")
    v = int(m.group(2), 8)
    if v > 0o77777:
        raise AsmError(f"octal constant '{tok}' too large")
    if m.group(1) == "-":
        return comp15(v)
    return v
