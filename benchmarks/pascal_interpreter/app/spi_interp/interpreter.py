from .errors import SpiRuntimeError
from .tokens import TokenType as T


class ActivationRecord:
    def __init__(self, name, type, level):
        self.name, self.type, self.nesting_level = name, type, level
        self.members = {}

    def __setitem__(self, k, v):
        self.members[k] = v

    def __getitem__(self, k):
        return self.members[k]

    def __str__(self):
        lines = [f"{self.nesting_level}: {self.type} {self.name}"]
        lines += [f"   {k:<20}: {v}" for k, v in self.members.items()]
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

    def __len__(self):
        return len(self._records)

    def __str__(self):
        return "CALL STACK\n" + "\n\n".join(str(ar) for ar in reversed(self._records)) + "\n"


class Interpreter:
    def __init__(self, tree, show_stack=False, out=print):
        self.tree, self.show_stack, self.out = tree, show_stack, out
        self.call_stack = CallStack()

    def _trace(self, text):
        if self.show_stack:
            self.out(text)

    def interpret(self):
        return self.visit(self.tree)

    def visit(self, node):
        return getattr(self, "visit_" + type(node).__name__)(node)

    def visit_Program(self, node):
        ar = ActivationRecord(node.name, "PROGRAM", 1)
        self.call_stack.push(ar)
        self._trace(f"ENTER: PROGRAM {node.name}")
        self._trace(str(self.call_stack))
        self.visit(node.block)
        self._trace(f"LEAVE: PROGRAM {node.name}")
        self._trace(str(self.call_stack))
        self.call_stack.pop()

    def visit_Block(self, node):
        self.visit(node.compound)  # declarations are static

    def visit_Compound(self, node):
        for c in node.children:
            self.visit(c)

    def visit_NoOp(self, node):
        pass

    def visit_Assign(self, node):
        value = self.visit(node.right)
        self.call_stack.peek()[node.left.value] = value

    def visit_Var(self, node):
        try:
            return self.call_stack.peek()[node.value]
        except KeyError:
            raise SpiRuntimeError(f"Variable '{node.value}' referenced before assignment")

    def visit_Num(self, node):
        return node.value

    def visit_UnaryOp(self, node):
        v = self.visit(node.expr)
        return -v if node.op.type is T.MINUS else +v

    def visit_BinOp(self, node):
        l, r = self.visit(node.left), self.visit(node.right)
        t = node.op.type
        if t is T.PLUS:
            return l + r
        if t is T.MINUS:
            return l - r
        if t is T.MUL:
            return l * r
        if r == 0:
            raise SpiRuntimeError("Division by zero")
        return l // r if t is T.INTEGER_DIV else l / r

    def visit_ProcedureCall(self, node):
        sym = node.proc_symbol
        args = [self.visit(a) for a in node.actual_params]  # evaluated in the caller
        ar = ActivationRecord(node.name, "PROCEDURE", len(self.call_stack) + 1)
        for p, v in zip(sym.params, args):
            ar[p.name] = v
        self.call_stack.push(ar)
        self._trace(f"ENTER: PROCEDURE {node.name}")
        self._trace(str(self.call_stack))
        self.visit(sym.block)
        self._trace(f"LEAVE: PROCEDURE {node.name}")
        self._trace(str(self.call_stack))
        self.call_stack.pop()
