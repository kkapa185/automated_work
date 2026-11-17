import unittest

from tests.helpers import prog, run
from spi_interp.errors import SpiRuntimeError
from spi_interp.interpreter import ActivationRecord, CallStack
from spi_interp.parser import parse
from spi_interp.semantic import SemanticAnalyzer
from spi_interp.interpreter import Interpreter


def final_globals(src):
    tree = SemanticAnalyzer().analyze(parse(src))
    it = Interpreter(tree)
    captured = {}
    orig = it.call_stack.pop

    def pop():
        captured.update(it.call_stack.peek().members)
        return orig()
    it.call_stack.pop = pop
    it.interpret()
    return captured


class InterpreterTests(unittest.TestCase):
    def g(self, body, decls="VAR x, y : INTEGER; r : REAL;"):
        return final_globals(prog(body, decls))

    def test_R9_arithmetic(self):
        m = self.g("x := 2 + 3 * 4; y := (2 + 3) * 4; r := 7 / 2")
        self.assertEqual((m["x"], m["y"], m["r"]), (14, 20, 3.5))

    def test_R9_div_and_float_div(self):
        m = self.g("x := 7 DIV 2; y := 20 div 3 div 2; r := 6 / 3")
        self.assertEqual((m["x"], m["y"], m["r"]), (3, 3, 2.0))
        self.assertIsInstance(m["r"], float)

    def test_R9_left_associativity(self):
        m = self.g("x := 10 - 3 - 2; y := 100 DIV 10 DIV 5")
        self.assertEqual((m["x"], m["y"]), (5, 2))

    def test_R9_unary(self):
        m = self.g("x := -3; y := - -3 + +2; r := -(1.5)")
        self.assertEqual((m["x"], m["y"], m["r"]), (-3, 5, -1.5))

    def test_R9_floor_div_negative(self):
        self.assertEqual(self.g("x := -7 DIV 2")["x"], -4)

    def test_R9_real_literal(self):
        self.assertEqual(self.g("r := 3.14 * 2")["r"], 6.28)

    def test_R9_division_by_zero(self):
        with self.assertRaises(SpiRuntimeError):
            self.g("x := 1 DIV 0")
        with self.assertRaises(SpiRuntimeError):
            self.g("r := 1 / 0")

    def test_R9_uninitialised_variable(self):
        with self.assertRaises(SpiRuntimeError) as c:
            self.g("x := y")
        self.assertEqual(str(c.exception), "RuntimeError: Variable 'y' referenced before assignment")

    def test_R9_procedure_params_isolated(self):
        out = run("""PROGRAM Main; VAR x : INTEGER;
        PROCEDURE P(x : INTEGER); BEGIN x := x + 1 END;
        BEGIN x := 5; P(x * 2) END.""", stack=True)
        self.assertIn("   x                   : 11", out)
        self.assertIn("   x                   : 5", out)

    def test_R9_nested_procedure_calls(self):
        src = """PROGRAM Main;
        PROCEDURE A(n : INTEGER);
          PROCEDURE B(m : INTEGER); VAR k : INTEGER; BEGIN k := m * 2 END;
        BEGIN B(n + 1) END;
        BEGIN A(1) END."""
        out = run(src, stack=True)
        self.assertIn("3: PROCEDURE B", out)
        self.assertIn("   k                   : 4", out)

    def test_R9_infinite_recursion_reported(self):
        from spi_interp.cli import run_source
        with self.assertRaises(SpiRuntimeError):
            run_source("PROGRAM P; PROCEDURE Q; BEGIN Q() END; BEGIN Q() END.")

    def test_R10_callstack_unit(self):
        s = CallStack()
        a = ActivationRecord("Main", "PROGRAM", 1)
        a["x"] = 1
        s.push(a)
        s.push(ActivationRecord("P", "PROCEDURE", 2))
        self.assertEqual(str(s), "CALL STACK\n2: PROCEDURE P\n\n1: PROGRAM Main\n   x                   : 1\n")

    def test_R10_exact_stack_output(self):
        out = run("""PROGRAM Main;
        VAR a : INTEGER; b : REAL;
        PROCEDURE P(n : INTEGER); VAR t : INTEGER; BEGIN t := n * 2 END;
        BEGIN a := 1; b := a / 2; P(a + 4) END.""", stack=True)
        n = lambda k, v: f"   {k:<20}: {v}\n"
        expected = (
            "ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n"
            "ENTER: PROCEDURE P\nCALL STACK\n2: PROCEDURE P\n" + n("n", 5) + "\n"
            "1: PROGRAM Main\n" + n("a", 1) + n("b", 0.5) + "\n"
            "LEAVE: PROCEDURE P\nCALL STACK\n2: PROCEDURE P\n" + n("n", 5) + n("t", 10) + "\n"
            "1: PROGRAM Main\n" + n("a", 1) + n("b", 0.5) + "\n"
            "LEAVE: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n" + n("a", 1) + n("b", 0.5) + "\n")
        self.assertEqual(out, expected)

    def test_R10_first_assignment_order(self):
        out = run(prog("b := 1; a := 2; b := 3", "VAR a, b : INTEGER;"), stack=True)
        last = out.split("LEAVE")[1]
        self.assertLess(last.index("   b "), last.index("   a "))
        self.assertIn("b                   : 3", last)

    def test_R10_no_stack_no_output(self):
        self.assertEqual(run(prog("a := 1", "VAR a : INTEGER;")), "")

    def test_R10_empty_program_stack(self):
        self.assertEqual(run("PROGRAM Main; BEGIN END.", stack=True),
                         "ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n"
                         "LEAVE: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n")

    def test_R10_procedure_without_params(self):
        out = run("PROGRAM M; PROCEDURE P; BEGIN END; BEGIN P(); P() END.", stack=True)
        self.assertEqual(out.count("ENTER: PROCEDURE P"), 2)
        self.assertEqual(out.count("LEAVE: PROCEDURE P"), 2)


if __name__ == "__main__":
    unittest.main()
