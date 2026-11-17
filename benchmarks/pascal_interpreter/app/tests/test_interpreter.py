import unittest
from helpers import *  # noqa
from spi_interp.interpreter import InterpreterError


def final_vars(src):
    """Return members printed in the last LEAVE record of the program."""
    out = run(src, stack=True)
    last = out.split("LEAVE: PROGRAM")[1].splitlines()[2:]
    d = {}
    for l in last:
        if l.startswith("   "):
            k, v = l[3:].split(":", 1)
            d[k.strip()] = v.strip()
    return d


def prog(body, decl="VAR x : REAL; y : INTEGER;"):
    return f"PROGRAM Main; {decl} BEGIN {body} END."


class InterpreterTests(unittest.TestCase):
    def test_r8_arithmetic(self):
        self.assertEqual(final_vars(prog("y := 2 + 3 * 4")), {'y': '14'})
        self.assertEqual(final_vars(prog("y := (2 + 3) * 4")), {'y': '20'})
        self.assertEqual(final_vars(prog("y := 10 - 4 - 3")), {'y': '3'})

    def test_r8_float_division(self):
        self.assertEqual(final_vars(prog("x := 7 / 2")), {'x': '3.5'})
        self.assertEqual(final_vars(prog("x := 4 / 2")), {'x': '2.0'})

    def test_r8_integer_division(self):
        self.assertEqual(final_vars(prog("y := 7 DIV 2")), {'y': '3'})
        self.assertEqual(final_vars(prog("y := 20 div 3 div 2")), {'y': '3'})

    def test_r8_unary(self):
        self.assertEqual(final_vars(prog("y := - - 5")), {'y': '5'})
        self.assertEqual(final_vars(prog("y := +3 - -2")), {'y': '5'})
        self.assertEqual(final_vars(prog("y := 5 - - 2 * 3")), {'y': '11'})

    def test_r8_real_literals(self):
        self.assertEqual(final_vars(prog("x := 3.14 * 2")), {'x': '6.28'})

    def test_r8_variables_and_reassign(self):
        self.assertEqual(final_vars(prog("y := 1; y := y + 1; x := y * 1.5")),
                         {'y': '2', 'x': '3.0'})

    def test_r9_stack_empty_program_exact(self):
        self.assertEqual(run("PROGRAM Main; BEGIN END.", stack=True),
                         "ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\n"
                         "LEAVE: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\n")

    def test_r9_stack_vars_in_assignment_order(self):
        out = run("PROGRAM Main; VAR a, b : INTEGER; BEGIN b := 1; a := 2 END.", stack=True)
        enter = "ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\n"
        leave = ("LEAVE: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n"
                 + line('b', 1) + line('a', 2) + "\n\n")
        self.assertEqual(out, enter + leave)
        self.assertEqual(line('b', 1), "   b                   : 1\n")

    def test_r9_stack_with_procedure_exact(self):
        src = ("PROGRAM Main; VAR a : INTEGER; PROCEDURE P(n : INTEGER); VAR t : REAL; "
               "BEGIN t := n / 2 END; BEGIN a := 4; P(a + 1) END.")
        exp = ("ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\n"
               "ENTER: PROCEDURE P\nCALL STACK\n2: PROCEDURE P\n" + line('n', 5)
               + "1: PROGRAM Main\n" + line('a', 4) + "\n\n"
               "LEAVE: PROCEDURE P\nCALL STACK\n2: PROCEDURE P\n" + line('n', 5) + line('t', 2.5)
               + "1: PROGRAM Main\n" + line('a', 4) + "\n\n"
               "LEAVE: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n" + line('a', 4) + "\n\n")
        self.assertEqual(run(src, stack=True), exp)

    def test_r9_nested_calls_levels_and_pop(self):
        src = ("PROGRAM Main; PROCEDURE A(x : INTEGER); PROCEDURE B(y : INTEGER); BEGIN END; "
               "BEGIN B(x * 2) END; BEGIN A(1); A(2) END.")
        out = run(src, stack=True)
        self.assertIn("3: PROCEDURE B\n" + line('y', 2) + "2: PROCEDURE A\n" + line('x', 1)
                      + "1: PROGRAM Main\n\n\n", out)
        self.assertIn("3: PROCEDURE B\n" + line('y', 4) + "2: PROCEDURE A\n" + line('x', 2), out)
        self.assertEqual(out.count("ENTER: PROCEDURE"), 4)
        self.assertEqual(out.count("LEAVE: PROCEDURE"), 4)

    def test_r9_params_assigned_in_order_multiple_groups(self):
        src = "PROGRAM Main; PROCEDURE P(a, b : INTEGER; c : REAL); BEGIN END; BEGIN P(1, 2, 3.5) END."
        self.assertIn("2: PROCEDURE P\n" + line('a', 1) + line('b', 2) + line('c', 3.5),
                      run(src, stack=True))

    def test_r9_no_stack_output_by_default(self):
        self.assertEqual(run("PROGRAM Main; BEGIN END."), "")

    def test_r9_long_name_not_truncated(self):
        name = "a" * 25
        out = run(f"PROGRAM M; VAR {name} : INTEGER; BEGIN {name} := 3 END.", stack=True)
        self.assertIn(f"   {name}: 3\n", out)

    def test_r8_procedure_uses_own_locals(self):
        src = ("PROGRAM Main; VAR x : INTEGER; PROCEDURE P(x : INTEGER); BEGIN x := x + 100 END; "
               "BEGIN x := 1; P(x) END.")
        out = run(src, stack=True)
        self.assertIn("2: PROCEDURE P\n" + line('x', 101) + "1: PROGRAM Main\n" + line('x', 1), out)

    def test_r12_division_by_zero(self):
        with self.assertRaises(InterpreterError):
            run(prog("x := 1 / 0"))
        with self.assertRaises(InterpreterError):
            run(prog("y := 1 DIV 0"))

    def test_r8_unassigned_read(self):
        with self.assertRaises(InterpreterError):
            run(prog("y := x + 1"))

    def test_r8_mixed_case_keywords(self):
        self.assertEqual(final_vars("Program Main; Var y : Integer; Begin y := 6 Div 4 End."), {'y': '1'})

    def test_r8_comments(self):
        self.assertEqual(final_vars("PROGRAM Main; VAR y : INTEGER; {c} BEGIN {x} y := 2 {y} END."), {'y': '2'})


if __name__ == '__main__':
    unittest.main()
