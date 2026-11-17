import unittest

from tests.helpers import prog, run
from spi_interp.errors import SemanticError
from spi_interp.parser import parse
from spi_interp.semantic import SemanticAnalyzer


def analyze(src, log=None):
    return SemanticAnalyzer(log).analyze(parse(src))


class SemanticTests(unittest.TestCase):
    def err(self, src):
        with self.assertRaises(SemanticError) as c:
            analyze(src)
        return str(c.exception)

    def test_R7_valid(self):
        analyze(prog("a := 1; b := a", "VAR a, b : INTEGER;"))

    def test_R7_duplicate_var(self):
        self.assertEqual(self.err("PROGRAM P;\nVAR a : INTEGER;\n    a : REAL;\nBEGIN END."),
                         "SemanticError: Duplicate id found -> Token(TokenType.ID, 'a', position=3:5)")

    def test_R7_duplicate_same_decl(self):
        self.assertIn("Duplicate id found", self.err("PROGRAM P; VAR a, a : INTEGER; BEGIN END."))

    def test_R7_shadowing_in_procedure_allowed(self):
        analyze("PROGRAM P; VAR a : INTEGER; PROCEDURE Q; VAR a : REAL; BEGIN a := 1 END; BEGIN END.")

    def test_R7_duplicate_param_and_local(self):
        self.assertIn("Duplicate id found",
                      self.err("PROGRAM P; PROCEDURE Q(a : INTEGER); VAR a : INTEGER; BEGIN END; BEGIN END."))

    def test_R7_undeclared_read_and_assign(self):
        self.assertEqual(self.err("PROGRAM P;\nBEGIN\n  x := 1\nEND."),
                         "SemanticError: Identifier not found -> Token(TokenType.ID, 'x', position=3:3)")
        self.assertIn("'y'", self.err(prog("x := y", "VAR x : INTEGER;")))

    def test_R7_case_sensitive_identifiers(self):
        self.assertIn("'A'", self.err(prog("A := 1", "VAR a : INTEGER;")))

    def test_R7_local_not_visible_outside(self):
        self.assertIn("Identifier not found",
                      self.err("PROGRAM P; PROCEDURE Q; VAR l : INTEGER; BEGIN END; BEGIN l := 1 END."))

    def test_R7_undeclared_procedure(self):
        self.assertIn("'Nope'", self.err(prog("Nope()")))

    def test_R7_analysis_before_execution(self):
        with self.assertRaises(SemanticError):
            run(prog("a := 1; b := 2", "VAR a : INTEGER;"), stack=True)

    def test_R8_arity_mismatch(self):
        src = "PROGRAM P; PROCEDURE Q(a : INTEGER); BEGIN END; BEGIN Q(1, 2) END."
        self.assertIn("Wrong number of arguments", self.err(src))
        self.assertIn("Wrong number of arguments", self.err("PROGRAM P; PROCEDURE Q(a : INTEGER); BEGIN END; BEGIN Q() END."))

    def test_R8_call_binds_symbol(self):
        t = analyze("PROGRAM P; PROCEDURE Q(a : INTEGER; b : REAL); BEGIN END; BEGIN Q(1, 2.0) END.")
        call = t.block.compound.children[0]
        self.assertEqual([p.name for p in call.proc_symbol.params], ["a", "b"])

    def test_R8_args_checked(self):
        self.assertIn("'zz'", self.err("PROGRAM P; PROCEDURE Q(a : INTEGER); BEGIN END; BEGIN Q(zz) END."))

    def test_R7_recursion_resolves(self):
        analyze("PROGRAM P; PROCEDURE Q; BEGIN Q() END; BEGIN END.")

    def test_R11_scope_log(self):
        lines = []
        analyze("PROGRAM P; VAR a : INTEGER; PROCEDURE Q(x : REAL); BEGIN END; BEGIN END.", lines.append)
        text = "\n".join(lines)
        for s in ("ENTER scope: global", "ENTER scope: Q", "LEAVE scope: Q", "LEAVE scope: global",
                  "INTEGER", "<x:REAL>", "<a:INTEGER>"):
            self.assertIn(s, text)


if __name__ == "__main__":
    unittest.main()
