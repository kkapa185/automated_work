"""SPI - a Simple Pascal Interpreter: lexer, parser, semantic analyzer, tree-walking interpreter."""
import sys
from enum import Enum


# ----------------------------------------------------------------- errors
class SpiError(Exception):
    """Base class; str(e) is the exact message printed by the CLI."""


class LexerError(SpiError):
    def __init__(self, char, line, column):
        super().__init__("LexerError: Lexer error on '%s' line: %d column: %d" % (char, line, column))


class ParserError(SpiError):
    def __init__(self, token):
        super().__init__("ParserError: Unexpected token -> %s" % token)


class SemanticError(SpiError):
    def __init__(self, message, token):
        super().__init__("SemanticError: %s -> %s" % (message, token))


class InterpreterError(SpiError):
    def __init__(self, message):
        super().__init__("RuntimeError: %s" % message)


# ----------------------------------------------------------------- lexer
class TokenType(Enum):
    PLUS = '+'
    MINUS = '-'
    MUL = '*'
    FLOAT_DIV = '/'
    LPAREN = '('
    RPAREN = ')'
    SEMI = ';'
    DOT = '.'
    COLON = ':'
    COMMA = ','
    PROGRAM = 'PROGRAM'
    INTEGER = 'INTEGER'
    REAL = 'REAL'
    INTEGER_DIV = 'DIV'
    VAR = 'VAR'
    PROCEDURE = 'PROCEDURE'
    BEGIN = 'BEGIN'
    END = 'END'
    ID = 'ID'
    INTEGER_CONST = 'INTEGER_CONST'
    REAL_CONST = 'REAL_CONST'
    ASSIGN = ':='
    EOF = 'EOF'


RESERVED = {
    'PROGRAM': TokenType.PROGRAM, 'INTEGER': TokenType.INTEGER, 'REAL': TokenType.REAL,
    'DIV': TokenType.INTEGER_DIV, 'VAR': TokenType.VAR, 'PROCEDURE': TokenType.PROCEDURE,
    'BEGIN': TokenType.BEGIN, 'END': TokenType.END,
}
SINGLE = {
    '+': TokenType.PLUS, '-': TokenType.MINUS, '*': TokenType.MUL, '/': TokenType.FLOAT_DIV,
    '(': TokenType.LPAREN, ')': TokenType.RPAREN, ';': TokenType.SEMI, '.': TokenType.DOT,
    ',': TokenType.COMMA,
}


class Token:
    def __init__(self, type, value, line=None, column=None):
        self.type = type
        self.value = value
        self.line = line
        self.column = column

    def __str__(self):
        return "Token(%s, %r, position=%s:%s)" % (self.type, self.value, self.line, self.column)

    __repr__ = __str__


class Lexer:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1

    @property
    def cur(self):
        return self.text[self.pos] if self.pos < len(self.text) else None

    def peek(self):
        p = self.pos + 1
        return self.text[p] if p < len(self.text) else None

    def advance(self):
        if self.cur == '\n':
            self.line += 1
            self.column = 0
        self.pos += 1
        self.column += 1

    def skip_ws_and_comments(self):
        while self.cur is not None:
            if self.cur.isspace():
                self.advance()
            elif self.cur == '{':
                line, col = self.line, self.column
                while self.cur is not None and self.cur != '}':
                    self.advance()
                if self.cur is None:
                    raise LexerError('{', line, col)
                self.advance()
            else:
                break

    def number(self):
        line, col = self.line, self.column
        s = ''
        while self.cur is not None and self.cur.isdigit() and self.cur.isascii():
            s += self.cur
            self.advance()
        if self.cur == '.' and self.peek() is not None and self.peek().isdigit() and self.peek().isascii():
            s += '.'
            self.advance()
            while self.cur is not None and self.cur.isdigit() and self.cur.isascii():
                s += self.cur
                self.advance()
            return Token(TokenType.REAL_CONST, float(s), line, col)
        return Token(TokenType.INTEGER_CONST, int(s), line, col)

    def ident(self):
        line, col = self.line, self.column
        s = ''
        while self.cur is not None and self.cur.isascii() and self.cur.isalnum():
            s += self.cur
            self.advance()
        tt = RESERVED.get(s.upper())
        if tt is not None:
            return Token(tt, s.upper(), line, col)
        return Token(TokenType.ID, s, line, col)

    def next_token(self):
        self.skip_ws_and_comments()
        c = self.cur
        if c is None:
            return Token(TokenType.EOF, None, self.line, self.column)
        if c.isascii() and c.isalpha():
            return self.ident()
        if c.isascii() and c.isdigit():
            return self.number()
        if c == ':' and self.peek() == '=':
            line, col = self.line, self.column
            self.advance()
            self.advance()
            return Token(TokenType.ASSIGN, ':=', line, col)
        if c == ':':
            tok = Token(TokenType.COLON, ':', self.line, self.column)
            self.advance()
            return tok
        if c in SINGLE:
            tok = Token(SINGLE[c], c, self.line, self.column)
            self.advance()
            return tok
        raise LexerError(c, self.line, self.column)


# ----------------------------------------------------------------- AST
class AST:
    pass


class Program(AST):
    def __init__(self, name, block, token):
        self.name, self.block, self.token = name, block, token


class Block(AST):
    def __init__(self, declarations, compound):
        self.declarations, self.compound = declarations, compound


class VarDecl(AST):
    def __init__(self, var_node, type_node):
        self.var_node, self.type_node = var_node, type_node


class Type(AST):
    def __init__(self, token):
        self.token, self.value = token, token.value


class Param(AST):
    def __init__(self, var_node, type_node):
        self.var_node, self.type_node = var_node, type_node


class ProcedureDecl(AST):
    def __init__(self, name, params, block, token):
        self.name, self.params, self.block, self.token = name, params, block, token


class Compound(AST):
    def __init__(self):
        self.children = []


class Assign(AST):
    def __init__(self, left, op, right):
        self.left, self.op, self.right = left, op, right


class ProcedureCall(AST):
    def __init__(self, name, args, token):
        self.name, self.args, self.token = name, args, token
        self.symbol = None


class Var(AST):
    def __init__(self, token):
        self.token, self.value = token, token.value


class Num(AST):
    def __init__(self, token):
        self.token, self.value = token, token.value


class BinOp(AST):
    def __init__(self, left, op, right):
        self.left, self.op, self.right = left, op, right


class UnaryOp(AST):
    def __init__(self, op, expr):
        self.op, self.expr = op, expr


class NoOp(AST):
    pass


# ----------------------------------------------------------------- parser
class Parser:
    def __init__(self, lexer):
        self.lexer = lexer
        self.tok = lexer.next_token()

    def error(self):
        raise ParserError(self.tok)

    def eat(self, tt):
        if self.tok.type == tt:
            self.tok = self.lexer.next_token()
        else:
            self.error()

    def program(self):
        self.eat(TokenType.PROGRAM)
        name_tok = self.tok
        self.eat(TokenType.ID)
        self.eat(TokenType.SEMI)
        block = self.block()
        self.eat(TokenType.DOT)
        return Program(name_tok.value, block, name_tok)

    def block(self):
        decls = []
        while self.tok.type == TokenType.VAR:
            self.eat(TokenType.VAR)
            while self.tok.type == TokenType.ID:
                decls.extend(self.var_decl())
                self.eat(TokenType.SEMI)
        while self.tok.type == TokenType.PROCEDURE:
            decls.append(self.procedure())
        return Block(decls, self.compound())

    def id_list(self):
        toks = [self.tok]
        self.eat(TokenType.ID)
        while self.tok.type == TokenType.COMMA:
            self.eat(TokenType.COMMA)
            toks.append(self.tok)
            self.eat(TokenType.ID)
        return toks

    def type_spec(self):
        t = self.tok
        if t.type in (TokenType.INTEGER, TokenType.REAL):
            self.eat(t.type)
            return Type(t)
        self.error()

    def var_decl(self):
        toks = self.id_list()
        self.eat(TokenType.COLON)
        ty = self.type_spec()
        return [VarDecl(Var(t), ty) for t in toks]

    def formal_parameters(self):
        params = []
        while True:
            toks = self.id_list()
            self.eat(TokenType.COLON)
            ty = self.type_spec()
            params.extend(Param(Var(t), ty) for t in toks)
            if self.tok.type == TokenType.SEMI:
                self.eat(TokenType.SEMI)
            else:
                break
        return params

    def procedure(self):
        self.eat(TokenType.PROCEDURE)
        name_tok = self.tok
        self.eat(TokenType.ID)
        params = []
        if self.tok.type == TokenType.LPAREN:
            self.eat(TokenType.LPAREN)
            params = self.formal_parameters()
            self.eat(TokenType.RPAREN)
        self.eat(TokenType.SEMI)
        block = self.block()
        self.eat(TokenType.SEMI)
        return ProcedureDecl(name_tok.value, params, block, name_tok)

    def compound(self):
        self.eat(TokenType.BEGIN)
        node = Compound()
        node.children.append(self.statement())
        while self.tok.type == TokenType.SEMI:
            self.eat(TokenType.SEMI)
            node.children.append(self.statement())
        self.eat(TokenType.END)
        return node

    def statement(self):
        t = self.tok.type
        if t == TokenType.BEGIN:
            return self.compound()
        if t == TokenType.ID:
            name_tok = self.tok
            self.eat(TokenType.ID)
            if self.tok.type == TokenType.LPAREN:
                self.eat(TokenType.LPAREN)
                args = []
                if self.tok.type != TokenType.RPAREN:
                    args.append(self.expr())
                    while self.tok.type == TokenType.COMMA:
                        self.eat(TokenType.COMMA)
                        args.append(self.expr())
                self.eat(TokenType.RPAREN)
                return ProcedureCall(name_tok.value, args, name_tok)
            op = self.tok
            self.eat(TokenType.ASSIGN)
            return Assign(Var(name_tok), op, self.expr())
        return NoOp()

    def expr(self):
        node = self.term()
        while self.tok.type in (TokenType.PLUS, TokenType.MINUS):
            op = self.tok
            self.eat(op.type)
            node = BinOp(node, op, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.tok.type in (TokenType.MUL, TokenType.INTEGER_DIV, TokenType.FLOAT_DIV):
            op = self.tok
            self.eat(op.type)
            node = BinOp(node, op, self.factor())
        return node

    def factor(self):
        t = self.tok
        if t.type in (TokenType.PLUS, TokenType.MINUS):
            self.eat(t.type)
            return UnaryOp(t, self.factor())
        if t.type in (TokenType.INTEGER_CONST, TokenType.REAL_CONST):
            self.eat(t.type)
            return Num(t)
        if t.type == TokenType.LPAREN:
            self.eat(TokenType.LPAREN)
            node = self.expr()
            self.eat(TokenType.RPAREN)
            return node
        if t.type == TokenType.ID:
            self.eat(TokenType.ID)
            return Var(t)
        self.error()

    def parse(self):
        node = self.program()
        if self.tok.type != TokenType.EOF:
            self.error()
        return node


# ----------------------------------------------------------------- symbols
class Symbol:
    def __init__(self, name, type=None):
        self.name, self.type = name, type


class BuiltinTypeSymbol(Symbol):
    def __str__(self):
        return self.name


class VarSymbol(Symbol):
    def __str__(self):
        return "<%s:%s>" % (self.name, self.type)


class ProcedureSymbol(Symbol):
    def __init__(self, name, params=None):
        super().__init__(name)
        self.params = params or []
        self.block = None

    def __str__(self):
        return "<%s(%s)>" % (self.name, ", ".join("%s:%s" % (p.name, p.type) for p in self.params))


class ScopedSymbolTable:
    def __init__(self, name, level, enclosing=None):
        self.name, self.level, self.enclosing = name, level, enclosing
        self.symbols = {}

    def define(self, sym):
        self.symbols[sym.name] = sym

    def lookup(self, name, current_only=False):
        sym = self.symbols.get(name)
        if sym is not None or current_only:
            return sym
        return self.enclosing.lookup(name) if self.enclosing else None

    def dump(self):
        lines = ["Scope name     : %s" % self.name, "Scope level    : %d" % self.level,
                 "Enclosing scope: %s" % (self.enclosing.name if self.enclosing else None),
                 "Scope (Scoped symbol table) contents", "------------------------------------"]
        lines += ["%7s: %s" % (k, v) for k, v in self.symbols.items()]
        return "\n".join(lines)


class SemanticAnalyzer:
    def __init__(self, show_scope=False, out=None):
        self.scope = None
        self.show_scope = show_scope
        self.out = out or sys.stdout

    def log(self, msg):
        if self.show_scope:
            print(msg, file=self.out)

    def _enter(self, name):
        level = self.scope.level + 1 if self.scope else 1
        self.scope = ScopedSymbolTable(name, level, self.scope)
        self.log("ENTER scope: %s" % name)
        if level == 1:
            self.scope.define(BuiltinTypeSymbol('INTEGER'))
            self.scope.define(BuiltinTypeSymbol('REAL'))

    def _leave(self):
        self.log(self.scope.dump())
        self.log("LEAVE scope: %s\n" % self.scope.name)
        self.scope = self.scope.enclosing

    def analyze(self, node):
        getattr(self, 'visit_' + type(node).__name__)(node)

    def visit_Program(self, node):
        self._enter('global')
        self.analyze(node.block)
        self._leave()

    def visit_Block(self, node):
        for d in node.declarations:
            self.analyze(d)
        self.analyze(node.compound)

    def _declare(self, var_node, type_node):
        tsym = self.scope.lookup(type_node.value)
        vsym = VarSymbol(var_node.value, tsym)
        if self.scope.lookup(vsym.name, current_only=True) is not None:
            raise SemanticError("Duplicate id found", var_node.token)
        self.scope.define(vsym)
        return vsym

    def visit_VarDecl(self, node):
        self._declare(node.var_node, node.type_node)

    def visit_ProcedureDecl(self, node):
        if self.scope.lookup(node.name, current_only=True) is not None:
            raise SemanticError("Duplicate id found", node.token)
        psym = ProcedureSymbol(node.name)
        self.scope.define(psym)
        self._enter(node.name)
        for p in node.params:
            psym.params.append(self._declare(p.var_node, p.type_node))
        psym.block = node.block
        self.analyze(node.block)
        self._leave()

    def visit_Compound(self, node):
        for c in node.children:
            self.analyze(c)

    def visit_NoOp(self, node):
        pass

    def visit_Assign(self, node):
        self.analyze(node.left)
        self.analyze(node.right)

    def visit_Var(self, node):
        if not isinstance(self.scope.lookup(node.value), VarSymbol):
            raise SemanticError("Identifier not found", node.token)

    def visit_Num(self, node):
        pass

    def visit_BinOp(self, node):
        self.analyze(node.left)
        self.analyze(node.right)

    def visit_UnaryOp(self, node):
        self.analyze(node.expr)

    def visit_ProcedureCall(self, node):
        sym = self.scope.lookup(node.name)
        if not isinstance(sym, ProcedureSymbol):
            raise SemanticError("Identifier not found", node.token)
        if len(sym.params) != len(node.args):
            raise SemanticError("Wrong number of arguments", node.token)
        for a in node.args:
            self.analyze(a)
        node.symbol = sym


# ----------------------------------------------------------------- interpreter
class ActivationRecord:
    def __init__(self, name, type, level):
        self.name, self.type, self.level = name, type, level
        self.members = {}

    def __setitem__(self, k, v):
        self.members[k] = v

    def __str__(self):
        lines = ["%d: %s %s" % (self.level, self.type, self.name)]
        lines += ["   %-20s: %s" % (k, v) for k, v in self.members.items()]
        return "\n".join(lines)


class CallStack:
    def __init__(self):
        self.records = []

    def push(self, r):
        self.records.append(r)

    def pop(self):
        return self.records.pop()

    def peek(self):
        return self.records[-1]

    def __str__(self):
        return "CALL STACK\n" + "".join(str(r) + "\n" for r in reversed(self.records)) + "\n\n"


class Interpreter:
    def __init__(self, tree, show_stack=False, out=None):
        self.tree = tree
        self.show_stack = show_stack
        self.out = out or sys.stdout
        self.stack = CallStack()

    def log(self, msg):
        if self.show_stack:
            self.out.write(msg + "\n")

    def _dump(self):
        if self.show_stack:
            self.out.write(str(self.stack))

    def interpret(self):
        self.visit(self.tree)

    def visit(self, node):
        return getattr(self, 'visit_' + type(node).__name__)(node)

    def visit_Program(self, node):
        self.log("ENTER: PROGRAM %s" % node.name)
        self.stack.push(ActivationRecord(node.name, 'PROGRAM', 1))
        self._dump()
        self.visit(node.block)
        self.log("LEAVE: PROGRAM %s" % node.name)
        self._dump()
        self.stack.pop()

    def visit_Block(self, node):
        self.visit(node.compound)

    def visit_VarDecl(self, node):
        pass

    def visit_ProcedureDecl(self, node):
        pass

    def visit_Compound(self, node):
        for c in node.children:
            self.visit(c)

    def visit_NoOp(self, node):
        pass

    def visit_Assign(self, node):
        value = self.visit(node.right)
        self.stack.peek()[node.left.value] = value

    def visit_Var(self, node):
        rec = self.stack.peek()
        if node.value not in rec.members:
            raise InterpreterError("Variable '%s' has no value (line %s column %s)"
                                   % (node.value, node.token.line, node.token.column))
        return rec.members[node.value]

    def visit_Num(self, node):
        return node.value

    def visit_UnaryOp(self, node):
        v = self.visit(node.expr)
        return -v if node.op.type == TokenType.MINUS else +v

    def visit_BinOp(self, node):
        a = self.visit(node.left)
        b = self.visit(node.right)
        t = node.op.type
        if t == TokenType.PLUS:
            return a + b
        if t == TokenType.MINUS:
            return a - b
        if t == TokenType.MUL:
            return a * b
        if b == 0:
            raise InterpreterError("Division by zero (line %s column %s)" % (node.op.line, node.op.column))
        if t == TokenType.FLOAT_DIV:
            return a / b
        return a // b

    def visit_ProcedureCall(self, node):
        sym = node.symbol
        values = [self.visit(a) for a in node.args]
        rec = ActivationRecord(node.name, 'PROCEDURE', self.stack.peek().level + 1)
        for formal, v in zip(sym.params, values):
            rec[formal.name] = v
        self.log("ENTER: PROCEDURE %s" % node.name)
        self.stack.push(rec)
        self._dump()
        self.visit(sym.block)
        self.log("LEAVE: PROCEDURE %s" % node.name)
        self._dump()
        self.stack.pop()


# ----------------------------------------------------------------- CLI
def run_source(text, show_scope=False, show_stack=False, out=None):
    tree = Parser(Lexer(text)).parse()
    SemanticAnalyzer(show_scope, out).analyze(tree)
    Interpreter(tree, show_stack, out).interpret()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    flags = {a for a in argv if a.startswith('--')}
    files = [a for a in argv if not a.startswith('--')]
    if len(files) != 1 or not flags <= {'--scope', '--stack'}:
        print("usage: spi <file.pas> [--scope] [--stack]", file=sys.stderr)
        return 2
    try:
        with open(files[0], encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print("error: cannot read %s: %s" % (files[0], e), file=sys.stderr)
        return 1
    try:
        run_source(text, '--scope' in flags, '--stack' in flags)
    except SpiError as e:
        sys.stdout.flush()
        print(str(e))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
