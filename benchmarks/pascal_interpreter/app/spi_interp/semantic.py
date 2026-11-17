from . import ast
from .errors import SemanticError
from .symbols import (BuiltinTypeSymbol, ProcedureSymbol, ScopedSymbolTable, VarSymbol)


class SemanticAnalyzer:
    def __init__(self, scope_log=None):
        """scope_log: optional callable(str) receiving scope tracing output."""
        self.scope = None
        self.log = scope_log or (lambda s: None)

    def _enter(self, name, level):
        self.scope = ScopedSymbolTable(name, level, self.scope)
        self.log(f"ENTER scope: {name}")
        return self.scope

    def _leave(self):
        self.log(self.scope.describe())
        self.log(f"LEAVE scope: {self.scope.name}")
        self.scope = self.scope.enclosing

    def _declare(self, symbol, token):
        if self.scope.lookup(symbol.name, current_scope_only=True) is not None:
            raise SemanticError("Duplicate id found", token)
        self.scope.insert(symbol)

    def analyze(self, tree):
        self.visit(tree)
        return tree

    def visit(self, node):
        return getattr(self, "visit_" + type(node).__name__)(node)

    def visit_Program(self, node):
        g = self._enter("global", 1)
        g.insert(BuiltinTypeSymbol("INTEGER"))
        g.insert(BuiltinTypeSymbol("REAL"))
        self.visit(node.block)
        self._leave()

    def visit_Block(self, node):
        for d in node.declarations:
            self.visit(d)
        self.visit(node.compound)

    def visit_VarDecl(self, node):
        ty = self.scope.lookup(node.type_node.name)
        self._declare(VarSymbol(node.var_node.value, ty), node.var_node.token)

    def visit_ProcedureDecl(self, node):
        proc = ProcedureSymbol(node.name)
        self._declare(proc, node.token)
        self._enter(node.name, self.scope.level + 1)
        for p in node.params:
            ty = self.scope.lookup(p.type_node.name)
            v = VarSymbol(p.var_node.value, ty)
            self._declare(v, p.var_node.token)
            proc.params.append(v)
        proc.block = node.block
        self.visit(node.block)
        self._leave()

    def visit_Compound(self, node):
        for c in node.children:
            self.visit(c)

    def visit_NoOp(self, node):
        pass

    def visit_Assign(self, node):
        self.visit(node.left)
        self.visit(node.right)

    def visit_Var(self, node):
        sym = self.scope.lookup(node.value)
        if not isinstance(sym, VarSymbol):
            raise SemanticError("Identifier not found", node.token)

    def visit_Num(self, node):
        pass

    def visit_UnaryOp(self, node):
        self.visit(node.expr)

    def visit_BinOp(self, node):
        self.visit(node.left)
        self.visit(node.right)

    def visit_ProcedureCall(self, node):
        sym = self.scope.lookup(node.name)
        if not isinstance(sym, ProcedureSymbol):
            raise SemanticError("Identifier not found", node.token)
        if len(sym.params) != len(node.actual_params):
            raise SemanticError("Wrong number of arguments", node.token)
        for a in node.actual_params:
            self.visit(a)
        node.proc_symbol = sym
