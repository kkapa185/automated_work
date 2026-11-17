"""AST node classes."""


class AST:
    pass


class BinOp(AST):
    def __init__(self, left, op, right):
        self.left, self.op, self.right = left, op, right


class UnaryOp(AST):
    def __init__(self, op, expr):
        self.op, self.expr = op, expr


class Num(AST):
    def __init__(self, token):
        self.token, self.value = token, token.value


class Var(AST):
    def __init__(self, token):
        self.token, self.value = token, token.value


class Assign(AST):
    def __init__(self, left, op, right):
        self.left, self.op, self.right = left, op, right


class NoOp(AST):
    pass


class Compound(AST):
    def __init__(self):
        self.children = []


class Type(AST):
    def __init__(self, token):
        self.token, self.value = token, token.value


class VarDecl(AST):
    def __init__(self, var_node, type_node):
        self.var_node, self.type_node = var_node, type_node


class Param(AST):
    def __init__(self, var_node, type_node):
        self.var_node, self.type_node = var_node, type_node


class ProcedureDecl(AST):
    def __init__(self, name, token, params, block):
        self.name, self.token, self.params, self.block = name, token, params, block


class ProcedureCall(AST):
    def __init__(self, name, args, token):
        self.name, self.args, self.token = name, args, token
        self.proc_symbol = None


class Block(AST):
    def __init__(self, declarations, compound):
        self.declarations, self.compound = declarations, compound


class Program(AST):
    def __init__(self, name, block):
        self.name, self.block = name, block
