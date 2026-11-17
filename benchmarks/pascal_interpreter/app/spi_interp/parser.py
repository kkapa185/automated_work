"""Recursive-descent parser producing an AST."""
from .lexer import TokenType as T
from . import ast_nodes as A


class ParserError(Exception):
    def __init__(self, token):
        self.token = token
        super().__init__(f"ParserError: Unexpected token -> {token}")


class Parser:
    def __init__(self, lexer):
        self.lexer = lexer
        self.tok = lexer.get_next_token()

    def eat(self, ttype):
        if self.tok.type is ttype:
            self.tok = self.lexer.get_next_token()
        else:
            raise ParserError(self.tok)

    def program(self):
        self.eat(T.PROGRAM)
        name = self.tok.value
        self.eat(T.ID)
        self.eat(T.SEMI)
        block = self.block()
        self.eat(T.DOT)
        self.eat(T.EOF)
        return A.Program(name, block)

    def block(self):
        decls = []
        if self.tok.type is T.VAR:
            self.eat(T.VAR)
            decls.extend(self.var_declarations())
        while self.tok.type is T.PROCEDURE:
            decls.append(self.procedure())
        return A.Block(decls, self.compound())

    def var_declarations(self):
        out = []
        while True:  # at least one declaration is required
            ids = [A.Var(self.tok)]
            self.eat(T.ID)
            while self.tok.type is T.COMMA:
                self.eat(T.COMMA)
                ids.append(A.Var(self.tok))
                self.eat(T.ID)
            self.eat(T.COLON)
            ty = self.type_spec()
            self.eat(T.SEMI)
            out.extend(A.VarDecl(v, ty) for v in ids)
            if self.tok.type is not T.ID:
                return out

    def type_spec(self):
        tok = self.tok
        if tok.type in (T.INTEGER, T.REAL):
            self.eat(tok.type)
            return A.Type(tok)
        raise ParserError(tok)

    def procedure(self):
        self.eat(T.PROCEDURE)
        tok = self.tok
        self.eat(T.ID)
        params = []
        if self.tok.type is T.LPAREN:
            self.eat(T.LPAREN)
            params = self.formal_parameters()
            self.eat(T.RPAREN)
        self.eat(T.SEMI)
        block = self.block()
        self.eat(T.SEMI)
        return A.ProcedureDecl(tok.value, tok, params, block)

    def formal_parameters(self):
        out = []
        while True:
            ids = [A.Var(self.tok)]
            self.eat(T.ID)
            while self.tok.type is T.COMMA:
                self.eat(T.COMMA)
                ids.append(A.Var(self.tok))
                self.eat(T.ID)
            self.eat(T.COLON)
            ty = self.type_spec()
            out.extend(A.Param(v, ty) for v in ids)
            if self.tok.type is T.SEMI:
                self.eat(T.SEMI)
            else:
                return out

    def compound(self):
        self.eat(T.BEGIN)
        node = A.Compound()
        node.children.append(self.statement())
        while self.tok.type is T.SEMI:
            self.eat(T.SEMI)
            node.children.append(self.statement())
        self.eat(T.END)
        return node

    def statement(self):
        if self.tok.type is T.BEGIN:
            return self.compound()
        if self.tok.type is T.ID:
            tok = self.tok
            self.eat(T.ID)
            if self.tok.type is T.LPAREN:
                self.eat(T.LPAREN)
                args = []
                if self.tok.type is not T.RPAREN:
                    args.append(self.expr())
                    while self.tok.type is T.COMMA:
                        self.eat(T.COMMA)
                        args.append(self.expr())
                self.eat(T.RPAREN)
                return A.ProcedureCall(tok.value, args, tok)
            op = self.tok
            self.eat(T.ASSIGN)
            return A.Assign(A.Var(tok), op, self.expr())
        return A.NoOp()

    def expr(self):
        node = self.term()
        while self.tok.type in (T.PLUS, T.MINUS):
            op = self.tok
            self.eat(op.type)
            node = A.BinOp(node, op, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.tok.type in (T.MUL, T.INTEGER_DIV, T.FLOAT_DIV):
            op = self.tok
            self.eat(op.type)
            node = A.BinOp(node, op, self.factor())
        return node

    def factor(self):
        tok = self.tok
        if tok.type in (T.PLUS, T.MINUS):
            self.eat(tok.type)
            return A.UnaryOp(tok, self.factor())
        if tok.type in (T.INTEGER_CONST, T.REAL_CONST):
            self.eat(tok.type)
            return A.Num(tok)
        if tok.type is T.LPAREN:
            self.eat(T.LPAREN)
            node = self.expr()
            self.eat(T.RPAREN)
            return node
        if tok.type is T.ID:
            self.eat(T.ID)
            return A.Var(tok)
        raise ParserError(tok)

    def parse(self):
        return self.program()
