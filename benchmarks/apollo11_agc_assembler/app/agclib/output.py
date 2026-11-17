"""Writers for the rope image, the symbol table and the listing."""

from __future__ import annotations

import json

from .model import BANK_WORDS, ROPE_ORDER, saddr


def rope_text(asm, name="program"):
    """Render the fixed-memory image in the ``.binsource`` text format."""
    out = [
        f"; AGC Block II core rope image: {name}",
        "; 36 fixed banks in order 2,3,0,1,4..43 (octal); 1024 words per bank;",
        "; words are 15-bit octal, '@' marks a word nothing was assembled into.",
    ]
    for bank in ROPE_ORDER:
        out.append(f"BANK={bank:o}")
        words = asm.fixed[bank]
        for i in range(0, BANK_WORDS, 8):
            out.append(" ".join("@" if w is None else f"{w:05o}" for w in words[i:i + 8]))
    return "\n".join(out) + "\n"


def symbols_dict(asm):
    out = {}
    for name, sym in asm.symbols.items():
        v = sym.val
        if v.space == "F":
            kind, bank, value = "fixed", v.lin // BANK_WORDS, saddr(v)
        elif v.space == "E":
            kind, value = "erasable", saddr(v)
            bank = (v.lin >> 8) if v.lin >= 0o1400 else None
        else:
            kind, bank, value = "constant", None, v.lin
        out[name] = {"value": value, "kind": kind, "bank": bank,
                     "file": sym.file, "line": sym.line}
    return out


def symbols_json(asm):
    return json.dumps(symbols_dict(asm), indent=1, sort_keys=True) + "\n"


def listing_text(asm):
    out = []
    for ln in asm.lines:
        out_words = getattr(ln, "out", [])
        loc = ""
        words = ""
        if out_words:
            bank, off, ws = out_words[0]
            s = off + 0o2000 if bank not in (2, 3) else off + 0o4000 + (0o2000 if bank == 3 else 0)
            loc = f"{bank:02o},{s:04o}"
            allw = []
            for _b, _o, w in out_words:
                allw.extend(w)
            words = " ".join(f"{w:05o}" for w in allw)
        out.append(f"{loc:8} {words:23} {ln.text}")
    return "\n".join(out) + "\n"


def summary_text(asm):
    lines = ["bank  checksum  words used"]
    for r in asm.reports:
        cs = "-" if r.checksum is None else f"{r.checksum:05o}"
        lines.append(f"{r.bank:4o}  {cs:>8}  {r.used:5d}")
    return "\n".join(lines) + "\n"
