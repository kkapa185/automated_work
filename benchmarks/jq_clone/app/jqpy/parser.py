"""Recursive-descent parser producing a tuple-based AST."""
from .lexer import tokenize, Tok, JQSyntaxError
from .values import _pint, _pfloat

ASSIGN_OPS = {"=", "|=", "+=", "-=", "*=", "/=", "%=", "//="}
LITERALS = {"null": None, "true": True, "false": False}
CMP_OPS = {"==", "!=", "<", "<=", ">", ">="}


def parse_number(text):
    if text.startswith("."):
        text = "0" + text
    if text.endswith("."):
        text = text[:-1]
    if any(c in text for c in ".eE"):
        return _pfloat(text)
    return _pint(text)


class Parser:
    def __init__(self, toks, src):
        self.toks = toks
        self.i = 0
        self.src = src

    # ---- helpers
    @property
    def tok(self):
        return self.toks[self.i]

    def line_of(self, pos):
        return self.src.count("\n", 0, pos) + 1

    def err(self, what=None):
        t = self.tok
        if t.kind == "eof":
            raise JQSyntaxError("syntax error, unexpected end of file")
        raise JQSyntaxError("syntax error, unexpected %s" % (what or repr(t.val if isinstance(t.val, str) else t.kind)))

    def isop(self, v):
        t = self.tok
        return t.kind == "op" and t.val == v

    def iskw(self, v):
        t = self.tok
        return t.kind == "kw" and t.val == v

    def eat_op(self, v):
        if not self.isop(v):
            self.err()
        self.i += 1

    def eat_kw(self, v):
        if not self.iskw(v):
            self.err()
        self.i += 1

    # ---- program
    def parse_program(self):
        directives = []
        mod = None
        if self.iskw("module"):
            self.i += 1
            mod = self.parse_postfix(False)
            self.eat_op(";")
        while self.iskw("import") or self.iskw("include"):
            kind = self.tok.val
            self.i += 1
            if self.tok.kind != "str":
                self.err()
            path = self.tok.val[0]
            self.i += 1
            alias = None
            if kind == "import":
                self.eat_kw("as")
                if self.tok.kind == "var":
                    alias = "$" + self.tok.val
                elif self.tok.kind == "ident":
                    alias = self.tok.val
                else:
                    self.err()
                self.i += 1
            meta = None
            if not self.isop(";"):
                meta = self.parse_postfix(False)
            self.eat_op(";")
            directives.append((kind, path, alias, meta))
        if self.tok.kind == "eof":
            body = ("id",)
        else:
            body = self.parse_pipe()
        if self.tok.kind != "eof":
            self.err()
        return mod, directives, body

    def parse_defs_only(self):
        """Parse a library file: module/imports followed by defs only."""
        mod, directives, _ = None, None, None
        return None

    # ---- grammar
    def parse_pipe(self, nc=False):
        if self.iskw("def"):
            fd = self.parse_funcdef()
            rest = self.parse_pipe(nc) if self.tok.kind != "eof" and not self.isop(")") else ("id",)
            return ("funcdef",) + fd + (rest,)
        if self.iskw("label"):
            self.i += 1
            if self.tok.kind != "var":
                self.err()
            name = self.tok.val
            self.i += 1
            self.eat_op("|")
            return ("label", name, self.parse_pipe(nc))
        lhs = self.parse_comma(nc)
        if self.isop("|"):
            self.i += 1
            return ("pipe", lhs, self.parse_pipe(nc))
        return lhs

    def parse_funcdef(self):
        self.eat_kw("def")
        t = self.tok
        if t.kind not in ("ident", "kw"):
            self.err()
        name = t.val
        self.i += 1
        params = []
        if self.isop("("):
            self.i += 1
            while True:
                t = self.tok
                if t.kind == "var":
                    params.append("$" + t.val)
                elif t.kind in ("ident", "kw"):
                    params.append(t.val)
                else:
                    self.err()
                self.i += 1
                if self.isop(";"):
                    self.i += 1
                    continue
                self.eat_op(")")
                break
        self.eat_op(":")
        body = self.parse_pipe()
        self.eat_op(";")
        return (name, params, body)

    def parse_comma(self, nc):
        lhs = self.parse_alt()
        while not nc and self.isop(","):
            self.i += 1
            lhs = ("comma", lhs, self.parse_alt())
        return lhs

    def parse_alt(self):
        lhs = self.parse_assign()
        if self.isop("//"):
            self.i += 1
            return ("alt", lhs, self.parse_alt())
        return lhs

    def parse_assign(self):
        lhs = self.parse_or()
        t = self.tok
        if t.kind == "op" and t.val in ASSIGN_OPS:
            self.i += 1
            rhs = self.parse_alt_noassign()
            lhs = ("assign", t.val, lhs, rhs)
            t = self.tok
            if t.kind == "op" and t.val in ASSIGN_OPS:
                self.err()
        return lhs

    def parse_alt_noassign(self):
        # rhs of an assignment: binds tighter than '//' (yacc precedence) but we
        # accept `a = b // c` as (a = b) // c by stopping at '//'
        return self.parse_or()

    def parse_or(self):
        lhs = self.parse_and()
        while self.iskw("or"):
            self.i += 1
            lhs = ("or", lhs, self.parse_and())
        return lhs

    def parse_and(self):
        lhs = self.parse_cmp()
        while self.iskw("and"):
            self.i += 1
            lhs = ("and", lhs, self.parse_cmp())
        return lhs

    def parse_cmp(self):
        lhs = self.parse_add()
        t = self.tok
        if t.kind == "op" and t.val in CMP_OPS:
            self.i += 1
            lhs = ("binop", t.val, lhs, self.parse_add())
            t = self.tok
            if t.kind == "op" and t.val in CMP_OPS:
                self.err()
        return lhs

    def parse_add(self):
        lhs = self.parse_mul()
        while self.tok.kind == "op" and self.tok.val in ("+", "-"):
            op = self.tok.val
            self.i += 1
            lhs = ("binop", op, lhs, self.parse_mul())
        return lhs

    def parse_mul(self):
        lhs = self.parse_unary()
        while self.tok.kind == "op" and self.tok.val in ("*", "/", "%"):
            op = self.tok.val
            self.i += 1
            lhs = ("binop", op, lhs, self.parse_unary())
        return lhs

    def parse_unary(self):
        if self.isop("-"):
            self.i += 1
            return ("neg", self.parse_unary())
        return self.parse_postfix(True)

    def parse_postfix(self, allow_as):
        node = self.parse_primary()
        while True:
            t = self.tok
            if t.kind == "field":
                self.i += 1
                node = ("index", node, ("lit", t.val))
            elif t.kind == "op" and t.val == ".":
                nt = self.toks[self.i + 1]
                if nt.kind == "str":
                    self.i += 1
                    node = ("index", node, self.parse_string(None))
                elif nt.kind == "op" and nt.val == "[":
                    self.i += 1
                else:
                    self.err()
            elif t.kind == "op" and t.val == "[":
                node = self.parse_bracket(node)
            elif t.kind == "op" and t.val == "?":
                self.i += 1
                node = ("try", node, None)
            elif t.kind == "kw" and t.val == "as" and allow_as:
                self.i += 1
                pats = [self.parse_pattern()]
                while self.isop("?//"):
                    self.i += 1
                    pats.append(self.parse_pattern())
                self.eat_op("|")
                body = self.parse_pipe()
                return ("bind", node, pats, body)
            else:
                return node

    def parse_bracket(self, target):
        self.eat_op("[")
        if self.isop("]"):
            self.i += 1
            return ("iter", target)
        if self.isop(":"):
            self.i += 1
            hi = self.parse_pipe()
            self.eat_op("]")
            return ("slice", target, None, hi)
        lo = self.parse_pipe()
        if self.isop(":"):
            self.i += 1
            if self.isop("]"):
                self.i += 1
                return ("slice", target, lo, None)
            hi = self.parse_pipe()
            self.eat_op("]")
            return ("slice", target, lo, hi)
        self.eat_op("]")
        return ("index", target, lo)

    def parse_string(self, fmt):
        t = self.tok
        self.i += 1
        parts = []
        for p in t.val:
            if isinstance(p, str):
                parts.append(p)
            else:
                sub = Parser(p, self.src)
                node = sub.parse_pipe()
                if sub.tok.kind != "eof":
                    sub.err()
                parts.append(node)
        if fmt is None and all(isinstance(p, str) for p in parts):
            return ("lit", "".join(parts))
        return ("str", fmt, parts)

    def parse_primary(self):
        t = self.tok
        k = t.kind
        if k == "num":
            self.i += 1
            return ("lit", parse_number(t.val))
        if k == "str":
            return self.parse_string(None)
        if k == "format":
            self.i += 1
            if self.tok.kind == "str":
                return self.parse_string(t.val)
            return ("format", t.val)
        if k == "field":
            self.i += 1
            return ("index", ("id",), ("lit", t.val))
        if k == "var":
            self.i += 1
            if t.val == "__loc__":
                return ("lit", {"file": "<top-level>", "line": self.line_of(t.pos)})
            return ("var", t.val)
        if k == "ident":
            self.i += 1
            if t.val == "break" and self.tok.kind == "var":
                nm = self.tok.val
                self.i += 1
                return ("break", nm)
            if t.val in LITERALS and not self.isop("("):
                return ("lit", LITERALS[t.val])
            args = []
            if self.isop("("):
                self.i += 1
                while True:
                    args.append(self.parse_pipe())
                    if self.isop(";"):
                        self.i += 1
                        continue
                    self.eat_op(")")
                    break
            return ("call", t.val, args)
        if k == "op":
            v = t.val
            if v == ".":
                self.i += 1
                if self.tok.kind == "str":
                    return ("index", ("id",), self.parse_string(None))
                return ("id",)
            if v == "..":
                self.i += 1
                return ("call", "recurse", [])
            if v == "(":
                self.i += 1
                e = self.parse_pipe()
                self.eat_op(")")
                return ("paren", e)
            if v == "[":
                self.i += 1
                if self.isop("]"):
                    self.i += 1
                    return ("array", None)
                e = self.parse_pipe()
                self.eat_op("]")
                return ("array", e)
            if v == "{":
                return self.parse_object()
            if v == "-":
                self.i += 1
                return ("neg", self.parse_postfix(True))
        if k == "kw":
            v = t.val
            if v == "if":
                return self.parse_if()
            if v == "try":
                self.i += 1
                body = self.parse_postfix_try()
                handler = None
                if self.iskw("catch"):
                    self.i += 1
                    handler = self.parse_postfix_try()
                return ("try", body, handler)
            if v == "reduce":
                self.i += 1
                src = self.parse_postfix(False)
                self.eat_kw("as")
                pats = self.parse_patterns()
                self.eat_op("(")
                init = self.parse_pipe()
                self.eat_op(";")
                upd = self.parse_pipe()
                self.eat_op(")")
                return ("reduce", src, pats, init, upd)
            if v == "foreach":
                self.i += 1
                src = self.parse_postfix(False)
                self.eat_kw("as")
                pats = self.parse_patterns()
                self.eat_op("(")
                init = self.parse_pipe()
                self.eat_op(";")
                upd = self.parse_pipe()
                ext = None
                if self.isop(";"):
                    self.i += 1
                    ext = self.parse_pipe()
                self.eat_op(")")
                return ("foreach", src, pats, init, upd, ext)
            if v == "def":
                return self.parse_pipe()
            if v == "label":
                return self.parse_pipe()
        if k == "ident" or (k == "kw" and False):
            pass
        self.err()

    def parse_postfix_try(self):
        # body of try / catch: a postfix term (no `as` binding), allowing unary minus
        if self.isop("-"):
            self.i += 1
            return ("neg", self.parse_postfix(False))
        return self.parse_postfix(False)

    def parse_if(self):
        self.eat_kw("if")
        cond = self.parse_pipe()
        self.eat_kw("then")
        then = self.parse_pipe()
        if self.iskw("elif"):
            self.toks[self.i] = Tok("kw", "if", self.tok.pos)
            els = self.parse_if_tail()
            return ("if", cond, then, els)
        if self.iskw("else"):
            self.i += 1
            els = self.parse_pipe()
            self.eat_kw("end")
            return ("if", cond, then, els)
        self.eat_kw("end")
        return ("if", cond, then, None)

    def parse_if_tail(self):
        # current token is a rewritten 'elif' (now 'if'); parse as nested if sharing the final 'end'
        self.eat_kw("if")
        cond = self.parse_pipe()
        self.eat_kw("then")
        then = self.parse_pipe()
        if self.iskw("elif"):
            self.toks[self.i] = Tok("kw", "if", self.tok.pos)
            return ("if", cond, then, self.parse_if_tail())
        if self.iskw("else"):
            self.i += 1
            els = self.parse_pipe()
            self.eat_kw("end")
            return ("if", cond, then, els)
        self.eat_kw("end")
        return ("if", cond, then, None)

    def parse_patterns(self):
        pats = [self.parse_pattern()]
        while self.isop("?//"):
            self.i += 1
            pats.append(self.parse_pattern())
        return pats

    def parse_pattern(self):
        t = self.tok
        if t.kind == "var":
            self.i += 1
            return ("pvar", t.val)
        if self.isop("["):
            self.i += 1
            elems = [self.parse_pattern()]
            while self.isop(","):
                self.i += 1
                elems.append(self.parse_pattern())
            self.eat_op("]")
            return ("parr", elems)
        if self.isop("{"):
            self.i += 1
            ents = []
            while True:
                t = self.tok
                if t.kind == "var":
                    self.i += 1
                    sub = None
                    if self.isop(":"):
                        self.i += 1
                        sub = self.parse_pattern()
                    ents.append((("var", t.val), sub))
                else:
                    if t.kind in ("ident", "kw"):
                        self.i += 1
                        key = ("lit", t.val)
                    elif t.kind == "str":
                        key = self.parse_string(None)
                    elif self.isop("("):
                        self.i += 1
                        key = self.parse_pipe()
                        self.eat_op(")")
                    else:
                        self.err()
                    self.eat_op(":")
                    ents.append((key, self.parse_pattern()))
                if self.isop(","):
                    self.i += 1
                    continue
                self.eat_op("}")
                break
            return ("pobj", ents)
        self.err()

    def parse_object(self):
        self.eat_op("{")
        ents = []
        if self.isop("}"):
            self.i += 1
            return ("object", ents)
        while True:
            t = self.tok
            val = None
            if t.kind == "var":
                self.i += 1
                if t.val == "__loc__":
                    key = ("lit", "__loc__")
                    val = ("lit", {"file": "<top-level>", "line": self.line_of(t.pos)})
                else:
                    key = ("lit", t.val)
                    val = ("var", t.val)
                if self.isop(":"):
                    self.err()
            elif t.kind in ("ident", "kw"):
                self.i += 1
                key = ("lit", t.val)
            elif t.kind == "num":
                self.i += 1
                key = ("lit", t.val)
                if not self.isop(":"):
                    self.err()
            elif t.kind == "str":
                key = self.parse_string(None)
            elif t.kind == "format":
                self.i += 1
                if self.tok.kind != "str":
                    self.err()
                key = self.parse_string(t.val)
            elif self.isop("("):
                self.i += 1
                key = self.parse_pipe()
                self.eat_op(")")
            else:
                self.err()
            if val is None:
                if self.isop(":"):
                    self.i += 1
                    val = self.parse_objval()
                else:
                    # shorthand {a} / {"a"} / {(..)}-invalid: value is .[key]
                    if t.kind == "op":
                        self.err()
                    val = ("index", ("id",), key)
            ents.append((key, val))
            if self.isop(","):
                self.i += 1
                continue
            self.eat_op("}")
            break
        return ("object", ents)

    def parse_objval(self):
        lhs = self.parse_alt()
        while self.isop("|"):
            self.i += 1
            lhs = ("pipe", lhs, self.parse_alt())
        return lhs


def parse(src):
    toks, _ = tokenize(src)
    return Parser(toks, src).parse_program()
