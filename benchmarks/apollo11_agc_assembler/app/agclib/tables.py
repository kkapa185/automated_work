"""Instruction, interpretive-opcode and pseudo-op tables for the Block II AGC."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Basic machine instructions
# ---------------------------------------------------------------------------
# kind:  'A12'  12-bit address field (0..0o7777)
#        'A10'  10-bit address field, erasable only (0..0o1777)
#        'F12'  address must be in fixed memory (>= 0o2000)  (TCF, BZF, BZMF)
#        'IO'   9-bit I/O channel number
#        'IMP'  implied-address instruction, complete word given by ``base``
#        'NOOP' special: TCF *+1 in fixed memory, CA A in erasable
# ext:   True for extracodes (must follow EXTEND).

BASIC = {
    # --- basic instructions
    "TC":    dict(kind="A12", base=0o00000, ext=False),
    "TCR":   dict(kind="A12", base=0o00000, ext=False),
    "CCS":   dict(kind="A10", base=0o10000, ext=False),
    "TCF":   dict(kind="F12", base=0o10000, ext=False),
    "DAS":   dict(kind="A10", base=0o20000, ext=False, dp=True),
    "LXCH":  dict(kind="A10", base=0o22000, ext=False),
    "INCR":  dict(kind="A10", base=0o24000, ext=False),
    "ADS":   dict(kind="A10", base=0o26000, ext=False),
    "CA":    dict(kind="A12", base=0o30000, ext=False),
    "CAE":   dict(kind="A12", base=0o30000, ext=False),
    "CAF":   dict(kind="A12", base=0o30000, ext=False),
    "CS":    dict(kind="A12", base=0o40000, ext=False),
    "INDEX": dict(kind="A12", base=0o50000, ext=None),   # legal with or without EXTEND
    "NDX":   dict(kind="A12", base=0o50000, ext=None),
    "DXCH":  dict(kind="A10", base=0o52000, ext=False, dp=True),
    "TS":    dict(kind="A10", base=0o54000, ext=False),
    "XCH":   dict(kind="A10", base=0o56000, ext=False),
    "AD":    dict(kind="A12", base=0o60000, ext=False),
    "MASK":  dict(kind="A12", base=0o70000, ext=False),
    # --- extracodes
    "READ":  dict(kind="IO", base=0o00000, ext=True),
    "WRITE": dict(kind="IO", base=0o01000, ext=True),
    "RAND":  dict(kind="IO", base=0o02000, ext=True),
    "WAND":  dict(kind="IO", base=0o03000, ext=True),
    "ROR":   dict(kind="IO", base=0o04000, ext=True),
    "WOR":   dict(kind="IO", base=0o05000, ext=True),
    "RXOR":  dict(kind="IO", base=0o06000, ext=True),
    "EDRUPT": dict(kind="A12", base=0o07000, ext=True),
    "DV":    dict(kind="A10", base=0o10000, ext=True),
    "BZF":   dict(kind="F12", base=0o10000, ext=True),
    "MSU":   dict(kind="A10", base=0o20000, ext=True),
    "QXCH":  dict(kind="A10", base=0o22000, ext=True),
    "AUG":   dict(kind="A10", base=0o24000, ext=True),
    "DIM":   dict(kind="A10", base=0o26000, ext=True),
    "DCA":   dict(kind="A12", base=0o30000, ext=True, dp=True),
    "DCS":   dict(kind="A12", base=0o40000, ext=True, dp=True),
        "SU":    dict(kind="A10", base=0o60000, ext=True),
    "BZMF":  dict(kind="F12", base=0o60000, ext=True),
    "MP":    dict(kind="A12", base=0o70000, ext=True),
    # --- implied-address codes
    "XXALQ": dict(kind="IMP", base=0o00000, ext=False),
    "XLQ":   dict(kind="IMP", base=0o00001, ext=False),
    "RETURN": dict(kind="IMP", base=0o00002, ext=False),
    "RELINT": dict(kind="IMP", base=0o00003, ext=False),
    "INHINT": dict(kind="IMP", base=0o00004, ext=False),
    "EXTEND": dict(kind="IMP", base=0o00006, ext=False),
    "RESUME": dict(kind="IMP", base=0o50017, ext=False),
    "TCAA":  dict(kind="IMP", base=0o54005, ext=False),
    "OVSK":  dict(kind="IMP", base=0o54000, ext=False),
    "COM":   dict(kind="IMP", base=0o40000, ext=False),
    "DOUBLE": dict(kind="IMP", base=0o60000, ext=False),
    "DDOUBL": dict(kind="IMP", base=0o20001, ext=False),
    "DCOM":  dict(kind="IMP", base=0o40001, ext=True),
    "ZL":    dict(kind="IMP", base=0o22007, ext=False),
    "ZQ":    dict(kind="IMP", base=0o22007, ext=True),
    "SQUARE": dict(kind="IMP", base=0o70000, ext=True),
    "DTCB":  dict(kind="IMP", base=0o52006, ext=False),
    "DTCF":  dict(kind="IMP", base=0o52005, ext=False),
    "NOOP":  dict(kind="NOOP", base=0, ext=False),
}

# ---------------------------------------------------------------------------
# Interpretive language
# ---------------------------------------------------------------------------
# Every interpretive operation has a 7-bit code ``c``; it is packed into an
# instruction word as the field ``c + 1`` (the interpreter's CCS subtracts the
# one back).  Two operations share a word, the first executed in bits 7-1 and
# the second in bits 14-8; the word is stored complemented (negative) so that
# the interpreter can tell it from a (positive) store code.

# Operations whose operand is an address-class word ("INDJUMP" table, 5-bit
# number).  A trailing '*' selects the indexed form.
INTERP_A = {
    "VLOAD": 0o00, "TAD": 0o01, "SIGN": 0o02, "VXSC": 0o03, "CGOTO": 0o04,
    "TLOAD": 0o05, "DLOAD": 0o06, "V/SC": 0o07,
    "SLOAD": 0o10, "SSP": 0o11, "PDDL": 0o12, "MXV": 0o13, "PDVL": 0o14,
    "CCALL": 0o15, "VXM": 0o16, "NORM": 0o17,
    "DMPR": 0o20, "DDV": 0o21, "BDDV": 0o22, "VAD": 0o24, "VSU": 0o25,
    "BVSU": 0o26, "DOT": 0o27,
    "VXV": 0o30, "VPROJ": 0o31, "DSU": 0o32, "BDSU": 0o33, "DAD": 0o34,
    "DMP": 0o36, "SETPD": 0o37,
}
INTERP_GSHIFT = 0o23

# Operands that must be present (no push-up possible).
INTERP_A_MANDATORY = {"SLOAD", "SETPD", "SSP", "CGOTO", "CCALL"}

# General shift mnemonics: name -> (right, round)
INTERP_SHIFT = {
    "SL": (0, 0), "SR": (1, 0), "SLR": (0, 1), "SRR": (1, 1),
    "VSL": (0, 0), "VSR": (1, 0),
}

# Unary operations: name -> 4-bit number ``u`` (code ``c = 8*u``).
INTERP_UNARY = {
    "SQRT": 0o01, "SIN": 0o02, "COS": 0o03, "ARCSIN": 0o04, "ARCCOS": 0o05, "ASIN": 0o04, "ACOS": 0o05, "SINE": 0o02, "COSINE": 0o03,
    "DSQ": 0o06, "ROUND": 0o07, "COMP": 0o10, "DCOMP": 0o10, "VCOMP": 0o10,
    "VDEF": 0o11, "UNIT": 0o12, "ABVAL": 0o13, "ABS": 0o13, "VSQ": 0o14,
    "STADR": 0o15, "RVQ": 0o16, "PUSH": 0o17, "EXIT": 0o00,
}

# Miscellaneous operations (4-bit number ``m`` and the bit ``b`` that selects
# index register 1 / the second member of a pair).  Code ``c = 8*m + 4*b + 2``.
# name -> (m, b, operand kind)
#   operand kinds:  'raw'   raw 15-bit operand (index value or ECADR)
#                   'cadr'  branch target (CADR), raw word
INTERP_MISC = {
    "AXT": (0o00, None, "raw"), "AXC": (0o01, None, "raw"),
    "LXA": (0o02, None, "ecadr"), "LXC": (0o03, None, "ecadr"),
    "SXA": (0o04, None, "ecadr"), "XCHX": (0o05, None, "ecadr"),
    "INCR": (0o06, None, "raw"), "TIX": (0o07, None, "cadr"),
    "XAD": (0o10, None, "ecadr"), "XSU": (0o11, None, "ecadr"),
    "BZE": (0o12, 0, "cadr"), "GOTO": (0o12, 1, "cadr"),
    "BPL": (0o13, 0, "cadr"), "BMN": (0o13, 1, "cadr"),
    "RTB": (0o14, 0, "cadr"), "CALRB": (0o14, 0, "cadr"), "BHIZ": (0o14, 1, "cadr"),
    "CALL": (0o15, 0, "cadr"), "STQ": (0o15, 1, "ecadr"), "ITA": (0o15, 1, "ecadr"),
    "BOVB": (0o17, 0, "cadr"), "BOV": (0o17, 1, "cadr"),
}
# mnemonics that take an index-register suffix ',1' or ',2'
INTERP_MISC_INDEXED = {"AXT", "AXC", "LXA", "LXC", "SXA", "XCHX", "INCR", "TIX", "XAD", "XSU"}

# Switch (flag) operations: number = 4*bit_op + branch_code
INTERP_SWITCH = {
    "BONSET": 0o00, "SETGO": 0o01, "BOFSET": 0o02, "SET": 0o03,
    "BONINV": 0o04, "INVGO": 0o05, "BOFINV": 0o06, "INVERT": 0o07,
    "BONCLR": 0o10, "CLRGO": 0o11, "BOFCLR": 0o12, "CLEAR": 0o13, "CLR": 0o13,
    "BON": 0o14, "BOFF": 0o16, "BOF": 0o16,
}
INTERP_SWITCH_M = 0o16     # miscellaneous-class slot of the switch operations

# Store codes: name -> type number (bits 12-14 of the store word)
INTERP_STORE = {
    "STORE": 0, "STODL": 3, "STODL*": 4, "STOVL": 5, "STOVL*": 6, "STCALL": 7,
}
# STORE may be suffixed with ',1' / ',2' on its operand giving types 1 and 2.

def interp_mnemonics():
    names = set(INTERP_UNARY) | set(INTERP_SWITCH) | set(INTERP_STORE) | {"STORE"}
    for n in INTERP_A:
        names.add(n)
        names.add(n + "*")
    for n in INTERP_SHIFT:
        names.add(n)
        names.add(n + "*")
    for n in ("SL", "SR"):
        for k in range(1, 5):
            names.add(f"{n}{k}")
            names.add(f"{n}{k}R")
    for n in ("VSL", "VSR"):
        for k in range(1, 9):
            names.add(f"{n}{k}")
    for n in INTERP_MISC:
        if n in INTERP_MISC_INDEXED:
            names.add(n + ",1")
            names.add(n + ",2")
        else:
            names.add(n)
    return names


INTERP_NAMES = interp_mnemonics()

# ---------------------------------------------------------------------------
# Pseudo-operations
# ---------------------------------------------------------------------------
PSEUDO = {
    "OCT", "OCTAL", "DEC", "DEC*", "2DEC", "2DEC*", "2OCT", "2OCTAL",
    "ADRES", "CADR", "FCADR", "ECADR", "GENADR", "REMADR", "2CADR", "2FCADR",
    "2BCADR", "BBCON", "BBCON*", "-2CADR", "-GENADR", "-ECADR", "-CADR",
    "-ADRES", "-FCADR", "-BBCON", "-REMADR", "-2FCADR", "-2BCADR",
    "VN", "NV", "MM", "DNPTR", "-DNPTR", "DNCHAN", "-DNCHAN",
    "1DNADR", "2DNADR", "3DNADR", "4DNADR", "5DNADR", "6DNADR",
    "-1DNADR", "-2DNADR", "-3DNADR", "-4DNADR", "-5DNADR", "-6DNADR",
    "ERASE", "EQUALS", "=", "=MINUS", "=PLUS", "EBANK=", "SBANK=", "BANK",
    "BLOCK", "SETLOC", "COUNT", "COUNT*", "MEMORY", "BNKSUM", "CHECKSUM",
    "SUBRO", "REMARK", "SPACE",
}

DNADR_CODES = {"1DNADR": 0, "2DNADR": 1, "3DNADR": 2, "4DNADR": 3, "5DNADR": 4, "6DNADR": 5}


def is_known_mnemonic(name):
    return name in BASIC or name in PSEUDO or name in INTERP_NAMES


# Names that need an operand: when one of these appears alone on a line inside
# interpretive code it is an operand symbol that happens to look like a mnemonic.
_NO_OPERAND_PSEUDO = {"BANK", "ERASE", "EQUALS", "=", "COUNT", "COUNT*", "CHECKSUM",
                      "SUBRO", "REMARK", "SPACE", "BBCON*"}
NEEDS_OPERAND = {n for n, i in BASIC.items() if i["kind"] in ("A12", "A10", "F12", "IO")} | (
    PSEUDO - _NO_OPERAND_PSEUDO)

# Data pseudo-ops producing exactly one word; they may stand in for an operand
# word of an interpretive operation ("AXT,1 / OCT 3").
ONE_WORD_DATA = {"OCT", "OCTAL", "DEC", "DEC*", "ADRES", "CADR", "ECADR", "FCADR",
                 "GENADR", "REMADR", "MM", "VN", "NV"}
