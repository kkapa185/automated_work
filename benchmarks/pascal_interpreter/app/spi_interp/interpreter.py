"""Tree-walking interpreter with a call stack of activation records."""
from .lexer import TokenType as T


class InterpreterError(Exception):
    def __init__(self, message):
        super().__init__(f"RuntimeError: {message}")


class ActivationRecord:
    def __init__(self, name, type, level):
        self.name, self.type, self.level = name, type, level
        self.members = {}

    def __setitem__(self, k, v):
        self.members[k] = v

    def __getitem__(self, k):
        return self.members[k]

    def get(self, k):
        return self.members.get(k)

    def __str__(self):
        lines = [f"{self.level}: {self.type} {self.name}"]
        for k, v in self.members.items():
            lines.append(f"   {k:<20}: {v}")
        return "\n".join(lines)


class CallStack:
    def __init__(self):
        self._records = []

    def push(self, ar):
        self._records.append(ar)

    def pop(self):
        return self._records.pop()

    def peek(self):
        return self._records[-1]

    def __str__(self):
        body = "\n".join(str(ar) for ar in reversed(self._records))
        return f"CALL STACK\n{body}\n\n"


class Interpreter:
    def __init__(self, tree, show_stack=False, out=print):
        self.tree = tree
        self.show_stack = show_stack
        self.out = out
        self.stack = CallStack()

    def _log(self, msg):
        if self.show_stack:
            self.out(msg)

    def interpret(self):
        self.visit_Program(self.tree)

    def visit(self, node):
        return getattr(self, 'visit_' + type(node).__name__)(node)

    def visit_Program(self, node):
        ar = ActivationRecord(node.name, 'PROGRAM', 1)
        self.stack.push(ar)
        self._log(f"ENTER: PROGRAM {node.name}")
        self._log(str(self.stack))
        self.visit(node.block.compound)
        self._log(f"LEAVE: PROGRAM {node.name}")
        self._log(str(self.stack))
        self.stack.pop()

    def visit_Compound(self, node):
        for c in node.children:
            self.visit(c)

    def visit_NoOp(self, node):
        pass

    def visit_Assign(self, node):
        value = self.visit(node.right)
        self.stack.peek()[node.left.value] = value

    def visit_Var(self, node):
        v = self.stack.peek().get(node.value)
        if v is None:
            raise InterpreterError(f"variable '{node.value}' has no value")
        return v

    def visit_Num(self, node):
        return node.value

    def visit_UnaryOp(self, node):
        v = self.visit(node.expr)
        return +v if node.op.type is T.PLUS else -v

    def visit_BinOp(self, node):
        a = self.visit(node.left)
        b = self.visit(node.right)
        t = node.op.type
        if t is T.PLUS:
            return a + b
        if t is T.MINUS:
            return a - b
        if t is T.MUL:
            return a * b
        if b == 0:
            raise InterpreterError("division by zero")
        if t is T.INTEGER_DIV:
            return a // b
        return float(a) / b

    def visit_ProcedureCall(self, node):
        sym = node.proc_symbol
        values = [self.visit(a) for a in node.args]
        ar = ActivationRecord(node.name, 'PROCEDURE', self.stack.peek().level + 1)
        for p, v in zip(sym.params, values):
            ar[p.name] = v
        self.stack.push(ar)
        self._log(f"ENTER: PROCEDURE {node.name}")
        self._log(str(self.stack))
        self.visit(sym.block_ast.compound)
        self._log(f"LEAVE: PROCEDURE {node.name}")
        self._log(str(self.stack))
        self.stack.pop()
