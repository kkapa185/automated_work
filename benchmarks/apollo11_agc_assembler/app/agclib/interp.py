"""Interpretive-language encoding.

Interpretive code is a stream of words.  An *operation word* packs two 7-bit
operation fields (first executed in bits 7-1, second in bits 14-8); each field
is the operation code plus one, and the whole word is stored complemented
(negative).  *Operand words* follow the operation word, one per operand, in
operation order.  A *store code* is a positive word holding a type in bits
12-14 and an erasable address, plus one.  See the README for the full
conventions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .expr import split_index
from .model import AsmError, Val, comp15, fbank_of
from .tables import (
    INTERP_A, INTERP_A_MANDATORY, INTERP_GSHIFT, INTERP_MISC,
    INTERP_MISC_INDEXED, INTERP_SHIFT, INTERP_STORE, INTERP_SWITCH,
    INTERP_SWITCH_M, INTERP_UNARY,
)


@dataclass
class Spec:
    """One expected operand word."""

    kind: str            # 'A', 'SHIFT', 'FLAG', 'ECADR', 'CADR', 'RAW'
    mandatory: bool
    opname: str
    idx: bool = False    # indexed (starred) operation
    extra: tuple = ()


@dataclass
class Op:
    name: str
    kind: str = "op"            # 'op' or 'store'
    code: int = 0
    specs: list = field(default_factory=list)
    exit: bool = False
    stadr: bool = False
    store_type: int = 0


_SHORT_RE = re.compile(r"^(SL|SR)([1-4])(R?)$")
_VSHORT_RE = re.compile(r"^(VSL|VSR)([1-8])$")


def classify(name):
    """Return an :class:`Op` describing interpretive mnemonic ``name``."""
    if name in INTERP_STORE:
        specs = []
        if name in ("STODL", "STOVL"):
            specs = [Spec("A", False, name)]
        elif name in ("STODL*", "STOVL*"):
            specs = [Spec("A", False, name, idx=True)]
        elif name == "STCALL":
            specs = [Spec("CADR", True, name)]
        return Op(name, "store", 0, specs, store_type=INTERP_STORE[name])
    if name in INTERP_UNARY:
        return Op(name, code=8 * INTERP_UNARY[name], exit=name == "EXIT",
                  stadr=name == "STADR")
    star = name.endswith("*")
    base = name[:-1] if star else name
    if base in INTERP_A:
        code = INTERP_A[base] * 4 + (2 if star else 0) + 1
        if base == "SSP":
            specs = [Spec("A", True, name, star), Spec("RAW", True, name)]
        elif base in ("CGOTO", "CCALL"):
            specs = [Spec("A", True, name, star), Spec("CADR", True, name)]
        else:
            specs = [Spec("A", base in INTERP_A_MANDATORY, name, star)]
        return Op(name, code=code, specs=specs)
    if base in INTERP_SHIFT:
        right, rnd = INTERP_SHIFT[base]
        code = INTERP_GSHIFT * 4 + (2 if star else 0) + 1
        return Op(name, code=code,
                  specs=[Spec("SHIFT", True, name, star, (right, rnd))])
    m = _SHORT_RE.match(name)
    if m:
        right = 1 if m.group(1) == "SR" else 0
        count = int(m.group(2))
        rnd = 1 if m.group(3) else 0
        code = ((count - 1) << 5) | (rnd << 4) | (right << 3) | 4
        return Op(name, code=code)
    m = _VSHORT_RE.match(name)
    if m:
        right = 1 if m.group(1) == "VSR" else 0
        count = int(m.group(2))
        code = ((count - 1) << 4) | (right << 3) | 4
        return Op(name, code=code)
    if name in INTERP_SWITCH:
        num = INTERP_SWITCH[name]
        code = 8 * INTERP_SWITCH_M + 2
        specs = [Spec("FLAG", True, name, extra=(num,))]
        if (num & 3) != 3:
            specs.append(Spec("CADR", True, name))
        return Op(name, code=code, specs=specs)
    root, comma, suffix = name.partition(",")
    if root in INTERP_MISC:
        m4, b, okind = INTERP_MISC[root]
        if root in INTERP_MISC_INDEXED:
            if suffix not in ("1", "2"):
                raise AsmError(f"'{root}' requires an index register suffix ',1' or ',2'")
            b = 1 if suffix == "1" else 0
        code = 8 * m4 + 4 * b + 2
        kind = {"raw": "RAW", "ecadr": "ECADR", "cadr": "CADR"}[okind]
        return Op(name, code=code, specs=[Spec(kind, True, name)])
    raise AsmError(f"unknown interpretive operation '{name}'")


def _address_a(v, what):
    """14-bit address for an address-class operand (before the +1 bias)."""
    if v.space == "N":
        a = v.lin
    elif v.space == "E":
        a = v.lin
    else:
        bank = v.lin // 0o2000
        off = v.lin % 0o2000
        if off == 0o1777:
            raise AsmError("interpretive operands cannot address the last word of a bank")
        a = ((fbank_of(bank) << 10) | off) & 0o37777
    return a


def encode_operand(spec, text, loc, asm):
    """Encode one operand word for ``spec`` from operand ``text`` at ``loc``."""
    kind = spec.kind
    if kind in ("A", "SHIFT"):
        expr, index = split_index(text)
        if spec.idx and index is None:
            raise AsmError(f"'{spec.opname}' requires an index register suffix ',1' or ',2'")
        if not spec.idx and index is not None:
            raise AsmError(f"operand index on '{spec.opname}' requires the starred operation")
        v = asm.ev(expr, loc)
        if kind == "SHIFT":
            if v.space != "N":
                raise AsmError("shift count must be a number")
            right, rnd = spec.extra
            count = v.lin
            field_ = 0o200 + count
            if not 0 <= field_ <= 0o377 or count > 0o175:
                raise AsmError(f"shift count {count} out of range")
            a = 0o20000 | (0o1000 if rnd else 0) | (0o400 if right else 0) | field_
        else:
            a = _address_a(v, spec.opname)
            if a < 0:
                raise AsmError("negative interpretive address")
        w = a + 1
        if w > 0o37777:
            raise AsmError("interpretive operand out of range")
        return comp15(w) if index == 2 else w
    v = asm.ev(text, loc)
    if kind == "FLAG":
        if v.space != "N" or v.lin < 0:
            raise AsmError("switch operand must be a flag number")
        n = v.lin
        num = spec.extra[0]
        word, bit = divmod(n, 15)
        a = (word << 8) | (num << 4) | bit
        if a > 0o77777:
            raise AsmError("flag number out of range")
        return a
    if kind == "ECADR":
        if v.space == "F":
            raise AsmError("operand must be an erasable address")
        if not 0 <= v.lin <= 0o3777:
            raise AsmError("erasable operand out of range")
        return v.lin
    if kind == "CADR":
        if v.space == "F":
            bank = v.lin // 0o2000
            return (fbank_of(bank) << 10) | (v.lin % 0o2000)
        if not 0 <= v.lin <= 0o7777:
            raise AsmError("branch target out of range")
        return v.lin
    if kind == "RAW":
        if v.space == "F":
            bank = v.lin // 0o2000
            return (fbank_of(bank) << 10) | (v.lin % 0o2000)
        n = v.lin
        if n < 0:
            n = comp15(-n)
        if n > 0o77777:
            raise AsmError("operand out of range")
        return n
    raise AsmError(f"internal error: bad operand kind {kind}")
