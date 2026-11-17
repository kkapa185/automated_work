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
        self.token, self.name = token, token.value


class Param(AST):
    def __init__(self, var_node, type_node):
        self.var_node, self.type_node = var_node, type_node


class ProcedureDecl(AST):
    def __init__(self, name, params, block, token):
        self.name, self.params, self.block, self.token = name, params, block, token


class Compound(AST):
    def __init__(self):
        self.children = []


class NoOp(AST):
    pass


class Assign(AST):
    def __init__(self, left, op, right):
        self.left, self.op, self.right = left, op, right


class ProcedureCall(AST):
    def __init__(self, name, actual_params, token):
        self.name, self.actual_params, self.token = name, actual_params, token
        self.proc_symbol = None  # bound by the semantic analyzer


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
