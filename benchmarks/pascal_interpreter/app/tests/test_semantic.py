import unittest
from helpers import *  # noqa
from spi_interp.lexer import Lexer
from spi_interp.parser import Parser
from spi_interp.semantic import SemanticAnalyzer, SemanticError


def analyze(s, log=None):
    SemanticAnalyzer(log).analyze(Parser(Lexer(s)).parse())


def err(s):
    with unittest.TestCase().assertRaises(SemanticError) as c:
        analyze(s)
    return str(c.exception)


class SemanticTests(unittest.TestCase):
    def test_r7_valid(self):
        analyze("PROGRAM p; VAR x:INTEGER; PROCEDURE Q(a:REAL); VAR b:REAL; BEGIN b := a END; BEGIN x := 1; Q(2.0) END.")

    def test_r7_duplicate_var(self):
        self.assertEqual(
            err("PROGRAM p;\nVAR x : INTEGER;\n  y, x : REAL;\nBEGIN END."),
            "SemanticError: Duplicate id found -> Token(TokenType.ID, 'x', position=3:6)")

    def test_r7_case_sensitive_ids_not_duplicate(self):
        analyze("PROGRAM p; VAR x, X : INTEGER; BEGIN x := 1; X := 2 END.")

    def test_r7_duplicate_param_and_local(self):
        self.assertIn("'a'", err("PROGRAM p; PROCEDURE Q(a:INTEGER); VAR a:INTEGER; BEGIN END; BEGIN END."))
        self.assertIn("'a'", err("PROGRAM p; PROCEDURE Q(a, a:INTEGER); BEGIN END; BEGIN END."))

    def test_r7_same_name_in_different_scopes_ok(self):
        analyze("PROGRAM p; VAR x:INTEGER; PROCEDURE Q(x:INTEGER); BEGIN x := 1 END; BEGIN x := 2 END.")

    def test_r7_undeclared_in_expression(self):
        self.assertEqual(
            err("PROGRAM p;\nVAR x : INTEGER;\nBEGIN\n  x := y + 1\nEND."),
            "SemanticError: Identifier not found -> Token(TokenType.ID, 'y', position=4:8)")

    def test_r7_undeclared_assignment_target(self):
        self.assertEqual(
            err("PROGRAM p; BEGIN\n z := 1 END."),
            "SemanticError: Identifier not found -> Token(TokenType.ID, 'z', position=2:2)")

    def test_r7_identifiers_case_sensitive(self):
        self.assertIn("'X'", err("PROGRAM p; VAR x : INTEGER; BEGIN X := 1 END."))

    def test_r7_local_not_visible_outside(self):
        self.assertIn("'t'", err("PROGRAM p; PROCEDURE Q; VAR t:INTEGER; BEGIN END; BEGIN t := 1 END."))

    def test_r7_undeclared_procedure(self):
        self.assertEqual(
            err("PROGRAM p; BEGIN Nope() END."),
            "SemanticError: Identifier not found -> Token(TokenType.ID, 'Nope', position=1:18)")

    def test_r7_arg_undeclared(self):
        self.assertIn("'q'", err("PROGRAM p; PROCEDURE Q(a:INTEGER); BEGIN END; BEGIN Q(q) END."))

    def test_r7_arg_count_mismatch(self):
        self.assertIn("Wrong number of arguments",
                      err("PROGRAM p; PROCEDURE Q(a:INTEGER); BEGIN END; BEGIN Q(1, 2) END."))

    def test_r7_procedure_declared_later_not_visible(self):
        self.assertIn("'B'", err("PROGRAM p; PROCEDURE A; BEGIN B() END; PROCEDURE B; BEGIN END; BEGIN END."))

    def test_r10_scope_output(self):
        out = []
        analyze("PROGRAM p; VAR x:INTEGER; PROCEDURE Q(a:REAL); BEGIN END; BEGIN END.", out.append)
        text = "\n".join(out)
        for s in ("ENTER scope: global", "ENTER scope: Q", "LEAVE scope: Q",
                  "LEAVE scope: global", "INTEGER", "REAL", "<x:INTEGER>", "<a:REAL>"):
            self.assertIn(s, text)
        self.assertLess(text.index("ENTER scope: Q"), text.index("LEAVE scope: Q"))


if __name__ == '__main__':
    unittest.main()
