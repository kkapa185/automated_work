class Symbol:
    def __init__(self, name, type=None):
        self.name, self.type = name, type

    def __str__(self):
        return f"<{self.name}>" if self.type is None else f"<{self.name}:{self.type.name}>"


class BuiltinTypeSymbol(Symbol):
    def __init__(self, name):
        super().__init__(name)


class VarSymbol(Symbol):
    pass


class ProcedureSymbol(Symbol):
    def __init__(self, name, params=None):
        super().__init__(name)
        self.params = params if params is not None else []  # list of VarSymbol
        self.block = None

    def __str__(self):
        return f"<{self.name}({', '.join(str(p) for p in self.params)})>"


class ScopedSymbolTable:
    def __init__(self, name, level, enclosing=None):
        self.name, self.level, self.enclosing = name, level, enclosing
        self._symbols = {}

    def insert(self, symbol):
        self._symbols[symbol.name] = symbol

    def lookup(self, name, current_scope_only=False):
        sym = self._symbols.get(name)
        if sym is not None or current_scope_only or self.enclosing is None:
            return sym
        return self.enclosing.lookup(name)

    def describe(self):
        lines = [f"Scope name     : {self.name}", f"Scope level    : {self.level}",
                 f"Enclosing scope: {self.enclosing.name if self.enclosing else None}",
                 "Scope (Scoped symbol table) contents", "-------------------------------------"]
        lines += [f"{k:>7}: {v}" for k, v in self._symbols.items()]
        return "\n".join(lines)
