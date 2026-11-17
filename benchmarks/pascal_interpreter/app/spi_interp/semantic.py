"""Scoped symbol tables and the semantic analyzer."""


class SemanticError(Exception):
    def __init__(self, message, token):
        self.token = token
        super().__init__(f"SemanticError: {message} -> {token}")


class Symbol:
    def __init__(self, name, type=None):
        self.name, self.type = name, type


class BuiltinTypeSymbol(Symbol):
    def __str__(self):
        return self.name


class VarSymbol(Symbol):
    def __str__(self):
        return f"<{self.name}:{self.type}>"


class ProcedureSymbol(Symbol):
    def __init__(self, name, params=None):
        super().__init__(name)
        self.params = params or []
        self.block_ast = None

    def __str__(self):
        return f"<ProcedureSymbol(name={self.name}, parameters={[p.name for p in self.params]})>"


class ScopedSymbolTable:
    def __init__(self, name, level, enclosing=None):
        self.name, self.level, self.enclosing = name, level, enclosing
        self._symbols = {}

    def insert(self, sym):
        self._symbols[sym.name] = sym

    def lookup(self, name, current_only=False):
        sym = self._symbols.get(name)
        if sym is not None or current_only:
            return sym
        return self.enclosing.lookup(name) if self.enclosing else None

    def describe(self):
        lines = [f"Scope name     : {self.name}", f"Scope level    : {self.level}",
                 f"Enclosing scope: {self.enclosing.name if self.enclosing else None}",
                 "Scope (Scoped symbol table) contents", "-------------------------------"]
        lines += [f"{k:>7}: {v}" for k, v in self._symbols.items()]
        return "\n".join(lines)


class SemanticAnalyzer:
    def __init__(self, scope_log=None):
        self.scope = None
        self.log = scope_log or (lambda s: None)

    def _enter(self, name):
        level = self.scope.level + 1 if self.scope else 1
        self.log(f"ENTER scope: {name}")
        self.scope = ScopedSymbolTable(name, level, self.scope)
        if level == 1:
            self.scope.insert(BuiltinTypeSymbol('INTEGER'))
            self.scope.insert(BuiltinTypeSymbol('REAL'))

    def _leave(self):
        self.log(self.scope.describe())
        self.log(f"LEAVE scope: {self.scope.name}")
        self.scope = self.scope.enclosing

    def _declare(self, sym, token):
        if self.scope.lookup(sym.name, current_only=True) is not None:
            raise SemanticError("Duplicate id found", token)
        self.scope.insert(sym)

    def analyze(self, tree):
        self.visit_Program(tree)

    def visit_Program(self, node):
        self._enter('global')
        self.visit_Block(node.block)
        self._leave()

    def visit_Block(self, node):
        for d in node.declarations:
            if hasattr(d, 'params'):
                self.visit_ProcedureDecl(d)
            else:
                self.visit_VarDecl(d)
        self.visit(node.compound)

    def visit_VarDecl(self, node):
        ty = self.scope.lookup(node.type_node.value)
        self._declare(VarSymbol(node.var_node.value, ty), node.var_node.token)

    def visit_ProcedureDecl(self, node):
        proc = ProcedureSymbol(node.name)
        proc.block_ast = node.block
        self._declare(proc, node.token)
        self._enter(node.name)
        for p in node.params:
            ty = self.scope.lookup(p.type_node.value)
            sym = VarSymbol(p.var_node.value, ty)
            self._declare(sym, p.var_node.token)
            proc.params.append(sym)
        self.visit_Block(node.block)
        self._leave()

    def visit(self, node):
        getattr(self, 'visit_' + type(node).__name__)(node)

    def visit_Compound(self, node):
        for c in node.children:
            self.visit(c)

    def visit_NoOp(self, node):
        pass

    def visit_Num(self, node):
        pass

    def _check_var(self, var):
        sym = self.scope.lookup(var.value)
        if not isinstance(sym, VarSymbol):
            raise SemanticError("Identifier not found", var.token)

    def visit_Var(self, node):
        self._check_var(node)

    def visit_Assign(self, node):
        self._check_var(node.left)
        self.visit(node.right)

    def visit_BinOp(self, node):
        self.visit(node.left)
        self.visit(node.right)

    def visit_UnaryOp(self, node):
        self.visit(node.expr)

    def visit_ProcedureCall(self, node):
        sym = self.scope.lookup(node.name)
        if not isinstance(sym, ProcedureSymbol):
            raise SemanticError("Identifier not found", node.token)
        for a in node.args:
            self.visit(a)
        if len(node.args) != len(sym.params):
            raise SemanticError("Wrong number of arguments", node.token)
        node.proc_symbol = sym
