"""Two-pass Block II AGC assembler.

Pass 1 walks the (include-expanded) source, tracks the location counter, defines
symbols and allocates every word of output.  Pass 2 evaluates operands against
the completed symbol table, encodes the words and fills in the bank checksums.
"""

from __future__ import annotations

import re
from collections import ChainMap, deque
from dataclasses import dataclass, field

from . import interp as ip
from .expr import evaluate, split_index
from .lexer import Line, read_source
from .model import (
    BANK_WORDS, ERASABLE_MAX, LAST_BANK, NUM_BANKS, AsmError, Undefined, Val,
    add1c, cadr_of, comp15, fbank_of, saddr, super_bits,
)
from .numbers import dec_dp, dec_sp, parse_int, parse_octal_word
from .tables import (
    BASIC, DNADR_CODES, INTERP_NAMES, NEEDS_OPERAND, ONE_WORD_DATA, PSEUDO,
    is_known_mnemonic,
)

_OFFSET = re.compile(r"^[+-][0-9]+D?$")


@dataclass
class Sym:
    val: Val
    file: str
    line: int


@dataclass
class Emit:
    """One group of words allocated in pass 1 and encoded in pass 2."""

    kind: str
    bank: int
    off: int
    line: Line
    data: tuple = ()
    words: list = field(default_factory=list)

    @property
    def loc(self):
        return Val("F", self.bank * BANK_WORDS + self.off)


@dataclass
class BankReport:
    bank: int
    checksum: int | None
    used: int


class Assembler:
    """Assembles an AGC program; see :meth:`assemble_file`."""

    def __init__(self):
        self.symbols: dict[str, Sym] = {}
        self.vals: dict[str, Val] = {}
        self.aliases: dict[str, Val] = {}
        self.symview = ChainMap(self.vals, self.aliases)
        self.diags: list[AsmError] = []
        self.warnings: list = []
        self.ctx = None
        self.final = False
        self.fixed = [[None] * BANK_WORDS for _ in range(NUM_BANKS)]
        self.occ = [bytearray(BANK_WORDS) for _ in range(NUM_BANKS)]
        self.hw = [0] * NUM_BANKS
        self.emits: list[Emit] = []
        self.lines: list[Line] = []
        self.deferred = []
        self.bnksum_banks: list[tuple[int, Line]] = []
        self.reports: list[BankReport] = []
        # location counter
        self.space = "E"
        self.bank = 0
        self.off = 0
        # state
        self.extend_pending = False
        self.imode = False
        self.pend: deque = deque()
        self.stadr_next = False
        self.exit_after = False
        self.ebank = ("num", 0)
        self.sbank = ("num", 0)
        self._eb_cache = {}

    # ------------------------------------------------------------------ utilities
    def error(self, msg, ln):
        self.diags.append(AsmError(msg, ln.file, ln.lineno))

    @property
    def ok(self):
        return not self.diags

    def cur_loc(self):
        if self.space == "E":
            return Val("E", self.off)
        return Val("F", self.bank * BANK_WORDS + self.off)

    def define(self, name, val, ln):
        old = self.vals.get(name)
        if old is not None and old != val:
            prev = self.symbols[name]
            raise AsmError(
                f"symbol '{name}' redefined (first defined at {prev.file}:{prev.line})")
        if old is None:
            self.symbols[name] = Sym(val, ln.file, ln.lineno)
            self.vals[name] = val

    def ev(self, text, loc=None, relative=True):
        try:
            return evaluate(text, self.symview, loc, relative)
        except Undefined as exc:
            alias = self.fuzzy_symbol(exc.name) if self.final else None
            if alias is None:
                raise
            self.aliases[exc.name] = self.vals[alias]
            self.warnings.append((self.ctx, f"undefined symbol '{exc.name}' resolved to '{alias}'"))
            return evaluate(text, self.symview, loc, relative)

    def fuzzy_symbol(self, name):
        """A unique defined symbol one edit away from ``name`` (typo tolerance).

        The transcribed sources contain a few mistyped references (for example
        ZEROEROR for ZEROERROR); the original assembler matched them because
        only eight characters were significant.
        """
        if len(name) < 5:
            return None
        found = []
        for cand in self.vals:
            if abs(len(cand) - len(name)) > 1:
                continue
            if _edit1(name, cand):
                found.append(cand)
                if len(found) > 1:
                    return None
        return found[0] if found else None

    def alloc(self, n):
        """Allocate ``n`` words at the location counter; returns (bank, off)."""
        if self.space != "F":
            raise AsmError("cannot assemble code or data into erasable memory")
        bank, off = self.bank, self.off
        if off + n > BANK_WORDS:
            self.off = BANK_WORDS
            raise AsmError(f"bank {bank:o} overflow")
        occ = self.occ[bank]
        clash = None
        for i in range(n):
            if occ[off + i]:
                clash = off + i
            occ[off + i] = 1
        self.off = off + n
        self.hw[bank] = max(self.hw[bank], self.off)
        if clash is not None:
            raise AsmError(f"location {bank:02o},{0o2000 + clash:o} already occupied")
        return bank, off

    def add_emit(self, kind, ln, n, data=()):
        bank, off = self.alloc(n)
        e = Emit(kind, bank, off, ln, data)
        self.emits.append(e)
        return e

    # ------------------------------------------------------------------ pass 1
    def assemble_file(self, path):
        """Assemble ``path``; returns True when no errors were found."""
        src_diags: list[AsmError] = []
        self.lines = read_source(path, src_diags, warns=self.warnings)
        for d in src_diags:
            if d.file is None:
                d.file, d.line = path, 0
        self.diags.extend(src_diags)
        if not self.lines and not self.diags:
            self.diags.append(AsmError(f"'{path}' is empty"))
        self.pass1()
        self.final = True
        self.resolve_deferred()
        self.pass2()
        self.checksums()
        self.diags.sort(key=lambda d: (d.file or "", d.line or 0))
        return self.ok

    def pass1(self):
        self.idx = 0
        while self.idx < len(self.lines):
            ln = self.lines[self.idx]
            self.idx += 1
            ln.loc = (self.space, self.bank, self.off)
            ln.out = []
            if ln.kind != "code":
                continue
            self.ctx = ln
            try:
                self.process(ln)
            except AsmError as exc:
                exc.file, exc.line = ln.file, ln.lineno
                self.diags.append(exc)
        try:
            self.flush_pending(None, final=True)
        except AsmError as exc:
            if self.lines:
                exc.file, exc.line = self.lines[-1].file, self.lines[-1].lineno
            self.diags.append(exc)

    # -- pending interpretive operands
    def flush_pending(self, ln, final=False):
        """Drop pending operands; mandatory ones are an error."""
        missing = [s for s in self.pend if s.mandatory]
        self.pend.clear()
        if self.exit_after:
            self.imode = False
            self.exit_after = False
        if missing:
            raise AsmError(f"missing operand for interpretive operation {missing[0].opname}")

    def operand_kind(self, ln):
        """Classify a line seen where an interpretive operand may appear.

        Returns 'operand' (the fields are an operand expression), 'data' (a
        one-word data pseudo-op standing in for an operand word) or None (an
        ordinary instruction/directive line, or a label-only line).
        """
        f = ln.fields
        if not f:
            return None
        t0 = f[0]
        if not is_known_mnemonic(t0):
            return "operand"
        rest = f[1:]
        if t0 in ONE_WORD_DATA and rest:
            if t0 in ("VN", "NV", "MM"):
                if re.fullmatch(r"\d+", rest[0]):
                    return "data"
            else:
                return "data"
        if t0 in NEEDS_OPERAND:
            if not rest and ln.label is None:
                return "operand"
            if rest and t0 in PSEUDO and all(_OFFSET.match(x) for x in rest):
                return "operand"
        return None

    def count_operand_lines(self):
        n = 0
        i = self.idx
        while i < len(self.lines):
            ln = self.lines[i]
            i += 1
            if ln.kind != "code":
                continue
            if self.operand_kind(ln) is None:
                break
            n += 1
        return n

    def process(self, ln):
        fields = ln.fields
        if self.pend:
            kind = self.operand_kind(ln)
            if not fields and ln.label is not None:
                self.define_label(ln)
                return
            if kind == "operand":
                spec = self.pend.popleft()
                if ln.label is not None:
                    self.define_label(ln)
                self.take_operand(spec, " ".join(fields), ln)
                if not self.pend and self.exit_after:
                    self.imode = False
                    self.exit_after = False
                return
            if kind == "data":
                self.pend.popleft()
                if not self.pend and self.exit_after:
                    self.imode = False
                    self.exit_after = False
            else:
                self.flush_pending(ln)
        if not fields:
            if ln.label is not None:
                self.define_label(ln)
            return
        op = fields[0]
        operand = " ".join(fields[1:])
        if op in PSEUDO:
            self.pseudo(ln, op, operand)
            return
        if op in INTERP_NAMES and (self.imode or op not in BASIC):
            self.interp_line(ln)
            return
        if basic_info(op) is not None:
            self.basic(ln, op, _basic_operand(fields[1:]))
            return
        if len(fields) == 1 and _OFFSET.match(op):
            self.define_label(ln)
            return          # a stray relative-location marker
        if ln.label is not None:
            self.define_label(ln)
        raise AsmError(f"unknown operation '{op}'")

    def define_label(self, ln, val=None):
        if ln.label is None:
            return
        if val is None:
            val = self.cur_loc()
        try:
            self.define(ln.label, val, ln)
        except AsmError as exc:
            exc.file, exc.line = ln.file, ln.lineno
            self.diags.append(exc)

    # -- basic instructions
    def basic(self, ln, op, operand):
        info = basic_info(op)
        self.imode = False
        self.define_label(ln)
        ext = info["ext"]
        if op.startswith("-"):
            ext = None
        if ext is True and not self.extend_pending:
            self.error(f"extracode '{op}' must follow EXTEND", ln)
        elif ext is False and self.extend_pending and op != "EXTEND":
            self.error(f"'{op}' is not an extracode but follows EXTEND", ln)
        if op == "EXTEND":
            self.extend_pending = True
        elif ext is not None:
            self.extend_pending = False
        if info["kind"] in ("IMP", "NOOP") and operand:
            self.error(f"'{op}' takes no operand", ln)
        self.add_emit("basic", ln, 1, (op, operand))
        if op in ("TC", "TCF") and operand == "INTPRET":
            self.imode = True

    # -- pseudo operations
    def pseudo(self, ln, op, operand):
        h = getattr(self, "p_" + _pyname(op), None)
        if h is None:
            raise AsmError(f"unsupported pseudo-operation '{op}'")
        h(ln, operand)

    def p_oct(self, ln, operand):
        self.define_label(ln)
        toks = operand.split()
        if len(toks) != 1:
            raise AsmError("OCT requires exactly one octal operand")
        w = parse_octal_word(toks[0])
        self.add_emit("data", ln, 1, ((w,),))

    p_octal = p_oct

    def p_2oct(self, ln, operand):
        self.define_label(ln)
        toks = operand.split()
        if len(toks) == 1 and re.fullmatch(r"[0-7]{10}", toks[0]):
            toks = [toks[0][:5], toks[0][5:]]
        if len(toks) != 2:
            raise AsmError("2OCT requires two five-digit octal words")
        words = (parse_octal_word(toks[0]), parse_octal_word(toks[1]))
        self.add_emit("data", ln, 2, (words,))

    p_2octal = p_2oct

    def p_dec(self, ln, operand):
        self.define_label(ln)
        if not operand:
            raise AsmError("DEC requires an operand")
        self.add_emit("data", ln, 1, ((dec_sp(operand),),))

    p_dec_star = p_dec

    def p_2dec(self, ln, operand):
        self.define_label(ln)
        if not operand:
            raise AsmError("2DEC requires an operand")
        self.add_emit("data", ln, 2, (tuple(dec_dp(operand)),))

    p_2dec_star = p_2dec

    def p_vn(self, ln, operand):
        self.define_label(ln)
        if not re.fullmatch(r"\d{1,5}", operand.strip()):
            raise AsmError("VN requires a decimal verb/noun number VVNN")
        n = int(operand.strip(), 10)
        verb, noun = divmod(n, 100)
        self.add_emit("data", ln, 1, (((verb << 7) | noun,),))

    p_nv = p_vn

    def p_mm(self, ln, operand):
        self.define_label(ln)
        if not re.fullmatch(r"\d{1,5}", operand.strip()):
            raise AsmError("MM requires a decimal mission-program number")
        self.add_emit("data", ln, 1, ((int(operand.strip(), 10),),))

    # address-type words (evaluated in pass 2)
    def _addr_op(self, ln, op, operand):
        self.define_label(ln)
        two = op.lstrip("-") in ("2CADR", "2FCADR", "2BCADR")
        if op.lstrip("-") in ("BBCON*",) and not operand:
            pass
        elif not operand and op.lstrip("-") != "BBCON*":
            raise AsmError(f"'{op}' requires an operand")
        self.add_emit("addr", ln, 2 if two else 1, (op, operand, self.ebank, self.sbank))

    def p_erase(self, ln, operand):
        if self.space != "E":
            raise AsmError("ERASE is only valid in erasable memory")
        toks = operand.split()
        start = self.off
        if not toks:
            count = 1
        elif len(toks) == 3 and toks[1] == "-":
            a = self.ev(toks[0], None, False)
            b = self.ev(toks[2], None, False)
            start, count = a.lin, b.lin - a.lin + 1
            if count < 1:
                raise AsmError("ERASE range is empty")
        elif len(toks) == 1 and toks[0][0] == "+":
            count = self.ev(toks[0], None, False).lin + 1
        else:
            count = self.ev(operand, None, False).lin + 1
        if start + count - 1 > ERASABLE_MAX:
            raise AsmError("erasable memory overflow")
        self.off = start
        self.define_label(ln)
        self.off = start + count

    def p_equals(self, ln, operand):
        if ln.label is None and not operand:
            return
        if not operand:
            self.define_label(ln)
            return
        self._equate(ln, operand, "equals")

    p_eq = p_equals

    def _equate(self, ln, operand, how):
        if ln.label is None:
            # an anonymous equate: validate only
            try:
                self.ev(operand, self.cur_loc())
            except Undefined:
                pass
            return
        loc = self.cur_loc()
        try:
            val = self.ev(operand, loc)
            val = self._equate_apply(val, how, loc)
        except Undefined:
            self.deferred.append((ln, operand, how, loc))
            return
        self.define(ln.label, val, ln)

    def _equate_apply(self, val, how, loc):
        if how == "minus":
            return val - loc if val.space == loc.space else Val.num(val.lin - loc.lin)
        if how == "plus":
            return val + Val.num(loc.lin) if val.space == "N" else val
        return val

    def p_minus_equals(self, ln, operand):   # '=MINUS'
        self._equate(ln, operand, "minus")

    def p_plus_equals(self, ln, operand):    # '=PLUS'
        self._equate(ln, operand, "plus")

    def p_ebank_equals(self, ln, operand):
        self.define_label(ln)
        if not operand:
            raise AsmError("EBANK= requires an operand")
        self.ebank = ("expr", operand, ln.file, ln.lineno)

    def p_sbank_equals(self, ln, operand):
        self.define_label(ln)
        if not operand:
            raise AsmError("SBANK= requires an operand")
        self.sbank = ("expr", operand, ln.file, ln.lineno)

    def p_count(self, ln, operand):
        self.define_label(ln)

    p_count_star = p_count

    def p_memory(self, ln, operand):
        # declares a memory region for the original assembler's accounting; the
        # label (if any) becomes the lower bound constant
        toks = operand.split()
        if ln.label is not None:
            try:
                lo = parse_int(toks[0]) if toks else 0
                self.define(ln.label, Val.num(lo or 0), ln)
            except AsmError as exc:
                exc.file, exc.line = ln.file, ln.lineno
                self.diags.append(exc)

    def p_remark(self, ln, operand):
        self.define_label(ln)

    p_space = p_subro = p_checksum = p_remark

    # -- location control
    def _save_pointer(self):
        if self.space == "F":
            self.hw[self.bank] = max(self.hw[self.bank], self.off)

    def p_bank(self, ln, operand):
        self.imode = False
        operand = operand.strip()
        if not operand:
            if self.space != "F":
                raise AsmError("BANK without operand outside fixed memory")
            self.skip_to_free()
            self.define_label(ln)
            return
        n = parse_int(operand)
        if n is None or not 0 <= n < NUM_BANKS:
            raise AsmError(f"bad bank number '{operand}'")
        self._save_pointer()
        self.space, self.bank = "F", n
        self.off = self.hw[n]
        self.define_label(ln)

    p_block = p_bank

    def skip_to_free(self):
        occ = self.occ[self.bank]
        while self.off < BANK_WORDS and occ[self.off]:
            self.off += 1

    def p_setloc(self, ln, operand):
        self.imode = False
        if not operand:
            raise AsmError("SETLOC requires an operand")
        v = self.ev(operand, None, False)
        self._save_pointer()
        if v.space == "E":
            self.space, self.off = "E", v.lin
        elif v.space == "F":
            self.space, self.bank, self.off = "F", v.bank, v.offset
        else:
            n = v.lin
            if self.space == "E" and 0 <= n <= ERASABLE_MAX and n < 0o4000:
                self.off = n
            elif 0o4000 <= n <= 0o7777:
                self.space = "F"
                self.bank = 2 + (n - 0o4000) // BANK_WORDS
                self.off = (n - 0o4000) % BANK_WORDS
            elif 0o2000 <= n <= 0o3777 and self.space == "F":
                self.off = n - 0o2000
            elif 0 <= n < 0o2000 and self.space == "F":
                self.space, self.off = "E", n
            else:
                raise AsmError(f"SETLOC address {n:o} out of range")
        self.define_label(ln)

    def p_bnksum(self, ln, operand):
        self.define_label(ln)
        n = parse_int(operand.strip()) if operand.strip() else None
        if n is None or not 0 <= n < NUM_BANKS:
            raise AsmError(f"bad bank number '{operand}' for BNKSUM")
        if any(b == n for b, _ in self.bnksum_banks):
            raise AsmError(f"duplicate BNKSUM for bank {n:o}")
        self.bnksum_banks.append((n, ln))
        if self.occ[n][BANK_WORDS - 1]:
            raise AsmError(f"bank {n:o}: checksum word location already occupied")
        self.occ[n][BANK_WORDS - 1] = 2
        self.hw[n] = max(self.hw[n], 0)

    # -- interpretive language ------------------------------------------------
    def interp_line(self, ln):
        self.imode = True
        self.define_label(ln)
        fields = ln.fields
        op1 = fields[0]
        rest = fields[1:]
        c1 = ip.classify(op1)
        if c1.kind == "store":
            if not rest:
                raise AsmError(f"'{op1}' requires a store address")
            self.interp_store(ln, c1, " ".join(rest))
            return
        c2 = None
        inline = None
        if rest:
            if rest[0] in INTERP_NAMES:
                if len(rest) > 1:
                    raise AsmError("too many fields on interpretive line")
                c2 = ip.classify(rest[0])
                if c2.kind == "store":
                    raise AsmError(f"store operation '{rest[0]}' cannot share a word")
            else:
                inline = " ".join(rest)
        specs = list(c1.specs) + (list(c2.specs) if c2 else [])
        word = comp15((((c2.code + 1) if c2 else 0) << 7) | (c1.code + 1))
        self.add_emit("data", ln, 1, ((word,),))
        if c1.exit or (c2 and c2.exit):
            self.exit_after = True
        if c1.stadr or (c2 and c2.stadr):
            self.stadr_next = True
        if inline is not None:
            if not specs:
                raise AsmError(f"'{op1}' takes no operand")
            self.take_operand(specs.pop(0), inline, ln)
        self.choose_operands(specs)

    def choose_operands(self, specs):
        """Decide which of ``specs`` receive operand lines (looking ahead)."""
        n = self.count_operand_lines()
        mandatory = [s for s in specs if s.mandatory]
        if n < len(mandatory):
            self.pend.clear()
            self.exit_after = False
            raise AsmError(f"missing operand for interpretive operation {mandatory[n].opname}")
        extra = n - len(mandatory)
        for s in specs:
            if s.mandatory:
                self.pend.append(s)
            elif extra > 0:
                self.pend.append(s)
                extra -= 1
        if not self.pend and self.exit_after:
            self.imode = False
            self.exit_after = False

    def interp_store(self, ln, res, operand):
        text, idx = split_index(operand)
        t = res.store_type
        if res.name == "STORE":
            if idx == 1:
                t = 1
            elif idx == 2:
                t = 2
        elif idx is not None:
            raise AsmError(f"'{res.name}' store address cannot be indexed")
        comp = self.stadr_next
        self.stadr_next = False
        self.add_emit("istore", ln, 1, (t, text, comp))
        self.choose_operands(list(res.specs))

    def take_operand(self, spec, text, ln):
        self.add_emit("iop", ln, 1, (spec, text))

    # ------------------------------------------------------------------ pass 1.5
    def resolve_deferred(self):
        pending = self.deferred
        self.deferred = []
        while pending:
            progress = False
            rest = []
            for ln, operand, how, loc in pending:
                try:
                    val = self._equate_apply(self.ev(operand, loc), how, loc)
                    self.define(ln.label, val, ln)
                    progress = True
                except Undefined:
                    rest.append((ln, operand, how, loc))
                except AsmError as exc:
                    exc.file, exc.line = ln.file, ln.lineno
                    self.diags.append(exc)
                    progress = True
            if not progress:
                for ln, operand, how, loc in rest:
                    try:
                        self.ev(operand, loc)
                    except AsmError as exc:
                        exc.file, exc.line = ln.file, ln.lineno
                        self.diags.append(exc)
                break
            pending = rest

    # ------------------------------------------------------------------ pass 2
    def ebank_value(self, ref):
        if ref[0] == "num":
            return ref[1]
        if ref in self._eb_cache:
            return self._eb_cache[ref]
        text = ref[1]
        v = self.ev(text, None, False)
        if v.space == "F":
            raise AsmError("EBANK= requires an erasable address")
        n = v.lin >> 8
        if not 0 <= n <= 7:
            raise AsmError("EBANK= address out of range")
        self._eb_cache[ref] = n
        return n

    def pass2(self):
        for e in self.emits:
            self.ctx = e.line
            try:
                words = self.encode(e)
            except AsmError as exc:
                exc.file, exc.line = e.line.file, e.line.lineno
                self.diags.append(exc)
                words = [0] * len(self.words_expected(e))
            e.words = words
            for i, w in enumerate(words):
                self.fixed[e.bank][e.off + i] = w
            e.line.out.append((e.bank, e.off, words))

    def words_expected(self, e):
        if e.kind == "data":
            return e.data[0]
        if e.kind == "addr":
            return [0, 0] if e.data[0].lstrip("-") in ("2CADR", "2FCADR", "2BCADR") else [0]
        return [0]

    def encode(self, e):
        k = e.kind
        if k == "data":
            return list(e.data[0])
        if k == "basic":
            return [self.encode_basic(e)]
        if k == "addr":
            return self.encode_addr(e)
        if k == "istore":
            t, text, comp = e.data
            v = self.ev(text, e.loc)
            if v.space == "F":
                raise AsmError("store address must be erasable")
            if not 0 <= v.lin <= ERASABLE_MAX:
                raise AsmError("store address out of range")
            w = ((t << 11) | v.lin) + 1
            return [comp15(w) if comp else w]
        if k == "iop":
            spec, text = e.data
            return [ip.encode_operand(spec, text, e.loc, self)]
        raise AsmError(f"internal error: bad emit kind {k}")

    def encode_basic(self, e):
        op, operand = e.data
        info = basic_info(op)
        kind = info["kind"]
        neg = op.startswith("-")
        if kind == "IMP":
            w = info["base"]
        elif kind == "NOOP":
            w = 0o10000 + saddr(e.loc) + 1
        else:
            if operand.strip():
                v = self.ev(operand, e.loc)
            else:
                v = Val.num(0)
            numeric = v.space == "N"
            if numeric:
                a = v.lin
                if a >= 0o10000:
                    # numeric addresses above 7777 are linear fixed addresses
                    a = 0o2000 + (a & 0o1777)
            else:
                a = saddr(v)
            if info.get("dp"):
                a += 1           # double-precision operations address the low-order word
            base = info["base"]
            if numeric:
                if a < -0o7777 or a > 0o7777 or (kind == "A10" and a > 0o1777):
                    raise AsmError(f"address {a:o} out of range for {op}")
                w = (base + a) & 0o77777
            else:
                if kind == "A12":
                    if not 0 <= a <= 0o7777:
                        raise AsmError(f"address {a:o} out of range for {op}")
                elif kind == "A10":
                    if not 0 <= a <= 0o1777:
                        raise AsmError(f"{op} requires an erasable address (got {a:o})")
                elif kind == "F12":
                    if not 0o2000 <= a <= 0o7777:
                        raise AsmError(f"{op} requires a fixed-memory address (got {a:o})")
                elif kind == "IO":
                    if not 0 <= a <= 0o777:
                        raise AsmError(f"channel number {a:o} out of range for {op}")
                w = base | a
        return comp15(w) if neg else w

    def encode_addr(self, e):
        op, operand, eb, sb = e.data
        neg = op.startswith("-")
        name = op.lstrip("-")
        if name == "BBCON*" and not operand:
            bank = LAST_BANK
            word = (fbank_of(bank) << 10) | _star_super(bank) | self.ebank_value(eb)
            return [comp15(word) if neg else word]
        if name in DNADR_CODES or name == "DNCHAN" or name == "DNPTR":
            v = self.ev(operand, e.loc)
            if name == "DNCHAN":
                code = 7
                low = v.lin
            elif name == "DNPTR":
                code = 6
                low = saddr(v)
            else:
                code = DNADR_CODES[name]
                low = v.lin
                if v.space == "F":
                    raise AsmError(f"{name} requires an erasable address")
            if not 0 <= low <= 0o7777:
                raise AsmError(f"{name} operand out of range")
            w = (code << 12) | low
            return [comp15(w) if neg else w]
        v = self.ev(operand, e.loc)
        if name in ("ADRES", "GENADR", "REMADR"):
            w = saddr(v)
            if not 0 <= w <= 0o7777:
                raise AsmError(f"{name} operand out of range")
            return [comp15(w) if neg else w]
        if name in ("CADR", "FCADR"):
            if v.space == "N":
                w = v.lin
            else:
                w = cadr_of(v)
            return [comp15(w) if neg else w]
        if name == "ECADR":
            if v.space == "F":
                raise AsmError("ECADR requires an erasable address")
            if not 0 <= v.lin <= ERASABLE_MAX:
                raise AsmError("ECADR operand out of range")
            return [comp15(v.lin) if neg else v.lin]
        if name in ("2CADR", "2FCADR", "2BCADR", "BBCON", "BBCON*"):
            if v.space != "F":
                raise AsmError(f"{name} requires a fixed-memory address")
            bank = v.lin // BANK_WORDS
            sup = _star_super(bank) if name == "BBCON*" else super_bits(bank)
            ebv = 0 if name == "2BCADR" else self.ebank_value(eb)
            bb = (fbank_of(bank) << 10) | sup | ebv
            if name.startswith("2"):
                ws = [saddr(v), bb]
                return [comp15(w) for w in ws] if neg else ws
            return [comp15(bb) if neg else bb]
        raise AsmError(f"unsupported pseudo-operation '{op}'")

    # ------------------------------------------------------------------ checksums
    def checksums(self):
        for bank, ln in self.bnksum_banks:
            words = self.fixed[bank]
            total = 0
            for i in range(BANK_WORDS - 1):
                w = words[i]
                if w is not None:
                    total = add1c(total, w)
            # choose X with total + X == bank number (one's complement)
            x = add1c(bank, comp15(total))
            if x == 0o77777:
                x = 0
            words[BANK_WORDS - 1] = x
            ln.out.append((bank, BANK_WORDS - 1, [x]))
        sums = {b for b, _ in self.bnksum_banks}
        for bank in range(NUM_BANKS):
            used = sum(1 for w in self.fixed[bank] if w is not None)
            cs = self.fixed[bank][BANK_WORDS - 1] if bank in sums else None
            self.reports.append(BankReport(bank, cs, used))


def _basic_operand(toks):
    """Operand of a basic instruction: a term plus ``+n`` / ``-n`` continuations.

    Anything after that is an un-hashed remark (the transcription has some).
    """
    if not toks:
        return ""
    out = [toks[0]]
    for t in toks[1:]:
        if t[0] in "+-" or out[-1] in ("+", "-"):
            out.append(t)
        else:
            break
    return " ".join(out)


def basic_info(op):
    """Table entry for a basic mnemonic, a numeric opcode digit, or a negated '-OP'."""
    info = BASIC.get(op)
    if info is not None:
        return info
    if len(op) == 1 and op in "01234567":
        return dict(kind="A12", base=int(op) * 0o10000, ext=None)
    if op.startswith("-") and op[1:] in BASIC and BASIC[op[1:]]["kind"] not in ("IMP", "NOOP"):
        return BASIC[op[1:]]
    return None


def _edit1(a, b):
    """True when ``a`` and ``b`` differ by exactly one insertion/deletion/substitution."""
    if a == b:
        return False
    if len(a) < len(b):
        a, b = b, a
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    i = 0
    while i < len(b) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i:]


def _star_super(bank):
    if bank >= 0o40:
        return 0o100
    if bank >= 0o30:
        return 0o060
    return 0


def _pyname(op):
    table = {
        "=": "eq", "=MINUS": "minus_equals", "=PLUS": "plus_equals",
        "EBANK=": "ebank_equals", "SBANK=": "sbank_equals",
        "COUNT*": "count_star", "DEC*": "dec_star", "2DEC*": "2dec_star",
        "BBCON*": "bbcon_star", "-2CADR": "neg_2cadr", "-GENADR": "neg_genadr",
    }
    if op in table:
        return table[op]
    return op.lower().replace("-", "neg_").replace("*", "_star")


# map the address-type pseudo-ops to the shared handler
def _bind_addr_ops():
    names = [
        "ADRES", "GENADR", "REMADR", "CADR", "FCADR", "ECADR", "2CADR",
        "2FCADR", "2BCADR", "BBCON", "BBCON*", "DNPTR", "DNCHAN",
        "1DNADR", "2DNADR", "3DNADR", "4DNADR", "5DNADR", "6DNADR",
    ]
    for n in names:
        for neg in ("", "-"):
            op = neg + n
            def handler(self, ln, operand, _op=op):
                self._addr_op(ln, _op, operand)
            setattr(Assembler, "p_" + _pyname(op), handler)


_bind_addr_ops()
for _n in ("-ECADR", "-CADR", "-ADRES", "-FCADR", "-BBCON", "-REMADR", "-2FCADR", "-2BCADR"):
    def _h(self, ln, operand, _op=_n):
        self._addr_op(ln, _op, operand)
    setattr(Assembler, "p_" + _pyname(_n), _h)
