from . import ast
from .errors import ParserError
from .lexer import Lexer
from .tokens import TokenType as T


class Parser:
    def __init__(self, lexer):
        self.lexer = lexer
        self.tok = lexer.get_next_token()

    def error(self):
        raise ParserError(self.tok)

    def eat(self, ttype):
        if self.tok.type is ttype:
            self.tok = self.lexer.get_next_token()
        else:
            self.error()

    def program(self):
        self.eat(T.PROGRAM)
        name_tok = self.tok
        self.eat(T.ID)
        self.eat(T.SEMI)
        block = self.block()
        self.eat(T.DOT)
        node = ast.Program(name_tok.value, block, name_tok)
        self.eat(T.EOF)
        return node

    def block(self):
        decls = []
        if self.tok.type is T.VAR:
            self.eat(T.VAR)
            while True:  # at least one declaration is required
                decls.extend(self.var_decl())
                self.eat(T.SEMI)
                if self.tok.type is not T.ID:
                    break
        while self.tok.type is T.PROCEDURE:
            self.eat(T.PROCEDURE)
            name_tok = self.tok
            self.eat(T.ID)
            params = []
            if self.tok.type is T.LPAREN:
                self.eat(T.LPAREN)
                params = self.formal_parameter_list()
                self.eat(T.RPAREN)
            self.eat(T.SEMI)
            body = self.block()
            self.eat(T.SEMI)
            decls.append(ast.ProcedureDecl(name_tok.value, params, body, name_tok))
        return ast.Block(decls, self.compound())

    def var_decl(self):
        toks = [self.tok]
        self.eat(T.ID)
        while self.tok.type is T.COMMA:
            self.eat(T.COMMA)
            toks.append(self.tok)
            self.eat(T.ID)
        self.eat(T.COLON)
        ty = self.type_spec()
        return [ast.VarDecl(ast.Var(t), ty) for t in toks]

    def type_spec(self):
        tok = self.tok
        if tok.type in (T.INTEGER, T.REAL):
            self.eat(tok.type)
            return ast.Type(tok)
        self.error()

    def formal_parameter_list(self):
        params = self.formal_parameters()
        while self.tok.type is T.SEMI:
            self.eat(T.SEMI)
            params.extend(self.formal_parameters())
        return params

    def formal_parameters(self):
        toks = [self.tok]
        self.eat(T.ID)
        while self.tok.type is T.COMMA:
            self.eat(T.COMMA)
            toks.append(self.tok)
            self.eat(T.ID)
        self.eat(T.COLON)
        ty = self.type_spec()
        return [ast.Param(ast.Var(t), ty) for t in toks]

    def compound(self):
        self.eat(T.BEGIN)
        node = ast.Compound()
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
            if self.tok.type is T.ASSIGN:
                op = self.tok
                self.eat(T.ASSIGN)
                return ast.Assign(ast.Var(tok), op, self.expr())
            if self.tok.type is T.LPAREN:
                self.eat(T.LPAREN)
                args = []
                if self.tok.type is not T.RPAREN:
                    args.append(self.expr())
                    while self.tok.type is T.COMMA:
                        self.eat(T.COMMA)
                        args.append(self.expr())
                self.eat(T.RPAREN)
                return ast.ProcedureCall(tok.value, args, tok)
            self.error()
        return ast.NoOp()

    def expr(self):
        node = self.term()
        while self.tok.type in (T.PLUS, T.MINUS):
            op = self.tok
            self.eat(op.type)
            node = ast.BinOp(node, op, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.tok.type in (T.MUL, T.INTEGER_DIV, T.FLOAT_DIV):
            op = self.tok
            self.eat(op.type)
            node = ast.BinOp(node, op, self.factor())
        return node

    def factor(self):
        tok = self.tok
        if tok.type in (T.PLUS, T.MINUS):
            self.eat(tok.type)
            return ast.UnaryOp(tok, self.factor())
        if tok.type in (T.INTEGER_CONST, T.REAL_CONST):
            self.eat(tok.type)
            return ast.Num(tok)
        if tok.type is T.LPAREN:
            self.eat(T.LPAREN)
            node = self.expr()
            self.eat(T.RPAREN)
            return node
        if tok.type is T.ID:
            self.eat(T.ID)
            return ast.Var(tok)
        self.error()


def parse(text):
    return Parser(Lexer(text)).program()
