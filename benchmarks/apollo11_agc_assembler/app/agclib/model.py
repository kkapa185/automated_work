"""Core data model: address values, banks, diagnostics.

AGC memory conventions used throughout (see README):

* Erasable memory is addressed linearly, 0..0o3777 ("ECADR" form).  Linear
  addresses 0..0o1377 are the unswitched registers; 0o1400..0o3777 are the
  switchable E-banks 3..7 (0o400 words each).  The 12-bit S-register address of
  a linear erasable address ``a`` is ``a`` if ``a < 0o1400`` else
  ``0o1400 + (a & 0o377)``.
* Fixed memory is addressed linearly as ``bank * 0o2000 + offset`` where bank is
  the octal bank number 0..0o43 and offset 0..0o1777.  Banks 2 and 3 are the
  fixed-fixed banks and appear at S-register addresses 0o4000-0o7777; every other
  bank appears (when selected) at 0o2000-0o3777.
"""

from __future__ import annotations

from dataclasses import dataclass

BANK_WORDS = 0o2000            # words per fixed bank
NUM_BANKS = 0o44               # banks 0..0o43 (36 banks)
ROPE_ORDER = [2, 3] + [b for b in range(NUM_BANKS) if b not in (2, 3)]
LAST_BANK = NUM_BANKS - 1
ERASABLE_MAX = 0o3777


class AsmError(Exception):
    """An error in the assembly source; carries file/line information."""

    def __init__(self, message, file=None, line=None):
        super().__init__(message)
        self.message = message
        self.file = file
        self.line = line

    def __str__(self):
        if self.file is not None:
            return f"{self.file}:{self.line}: {self.message}"
        return self.message


class Undefined(AsmError):
    """Raised when an expression references an undefined symbol."""

    def __init__(self, name):
        super().__init__(f"undefined symbol '{name}'")
        self.name = name


@dataclass(frozen=True)
class Val:
    """A value: a plain number ('N'), erasable address ('E') or fixed address ('F')."""

    space: str
    lin: int

    @staticmethod
    def num(n):
        return Val("N", n)

    @property
    def is_num(self):
        return self.space == "N"

    @property
    def bank(self):
        """Fixed bank number (F) or E-bank (E, for switchable erasable); else None."""
        if self.space == "F":
            return self.lin // BANK_WORDS
        if self.space == "E":
            return self.lin >> 8
        return None

    @property
    def offset(self):
        """Offset inside the fixed bank (0..0o1777)."""
        return self.lin % BANK_WORDS

    def __add__(self, other):
        o = other if isinstance(other, Val) else Val.num(other)
        if self.space == "N":
            return Val(o.space, self.lin + o.lin)
        if o.space == "N":
            return Val(self.space, self.lin + o.lin)
        raise AsmError("cannot add two addresses")

    def __sub__(self, other):
        o = other if isinstance(other, Val) else Val.num(other)
        if o.space == "N":
            return Val(self.space, self.lin - o.lin)
        if o.space == self.space:
            return Val.num(self.lin - o.lin)
        raise AsmError("cannot subtract addresses from different memory spaces")


def fbank_of(bank):
    """FBANK register value for fixed bank ``bank`` (banks 0o40-0o43 alias FBANK 0o30-0o33)."""
    return bank if bank <= 0o37 else bank - 0o10


def super_bits(bank):
    """Super-bank bits (channel 7 bits 7-5 convention) for a bank number."""
    if bank >= 0o40:
        return 0o100
    return 0


def saddr(v):
    """12-bit S-register address of a value (numbers pass through)."""
    if v.space == "N":
        return v.lin
    if v.space == "E":
        return v.lin if v.lin < 0o1400 else 0o1400 + (v.lin & 0o377)
    bank = v.lin // BANK_WORDS
    off = v.lin % BANK_WORDS
    if bank in (2, 3):
        return v.lin
    return 0o2000 + off


def cadr_of(v):
    """CADR (FBANK in bits 15-11, 10-bit bank-relative offset)."""
    if v.space != "F":
        raise AsmError("CADR requires a fixed-memory address")
    bank = v.lin // BANK_WORDS
    return (fbank_of(bank) << 10) | (v.lin % BANK_WORDS)


def ecadr_of(v):
    """ECADR (EBANK in bits 11-9, low 8 bits of the address)."""
    if v.space == "F":
        raise AsmError("ECADR requires an erasable address")
    if not 0 <= v.lin <= ERASABLE_MAX:
        raise AsmError(f"erasable address {v.lin:o} out of range")
    return v.lin


def comp15(w):
    """One's complement of a 15-bit word."""
    return (~w) & 0o77777


def add1c(a, b):
    """15-bit one's-complement addition with end-around carry."""
    s = a + b
    if s > 0o77777:
        s = (s & 0o77777) + 1
    return s & 0o77777
