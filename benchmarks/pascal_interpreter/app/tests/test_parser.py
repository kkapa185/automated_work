import unittest

from tests.helpers import prog
from spi_interp import ast
from spi_interp.errors import LexerError, ParserError
from spi_interp.parser import parse


class ParserTests(unittest.TestCase):
    def err(self, src, cls=ParserError):
        with self.assertRaises(cls) as c:
            parse(src)
        return str(c.exception)

    def test_R5_program_structure(self):
        t = parse("PROGRAM P; VAR a, b : INTEGER; x : REAL; "
                  "PROCEDURE Q(a, b : INTEGER; c : REAL); BEGIN END; "
                  "PROCEDURE R; BEGIN END; BEGIN a := 1 END.")
        self.assertEqual(t.name, "P")
        decls = t.block.declarations
        self.assertEqual([type(d).__name__ for d in decls],
                         ["VarDecl", "VarDecl", "VarDecl", "ProcedureDecl", "ProcedureDecl"])
        self.assertEqual([p.var_node.value for p in decls[3].params], ["a", "b", "c"])
        self.assertEqual(decls[4].params, [])

    def test_R5_precedence_and_associativity(self):
        t = parse(prog("x := 1 - 2 - 3 * 4"))
        e = t.block.compound.children[0].right
        self.assertEqual(e.op.value, "-")
        self.assertEqual(e.left.op.value, "-")
        self.assertEqual(e.right.op.value, "*")

    def test_R5_unary_and_parens(self):
        t = parse(prog("x := -(+3)"))
        e = t.block.compound.children[0].right
        self.assertIsInstance(e, ast.UnaryOp)
        self.assertIsInstance(e.expr, ast.UnaryOp)

    def test_R5_empty_statements_and_calls(self):
        t = parse(prog(";; P(); P(1, 2+3);"))
        kinds = [type(c).__name__ for c in t.block.compound.children]
        self.assertEqual(kinds, ["NoOp", "NoOp", "ProcedureCall", "ProcedureCall", "NoOp"])

    def test_R5_nested_compound(self):
        parse(prog("BEGIN BEGIN END; END"))

    def test_R5_lowercase_keywords(self):
        parse("program p; var a : integer; begin a := 1 end.")

    def test_R6_missing_dot(self):
        self.assertEqual(self.err("PROGRAM P; BEGIN END"),
                         "ParserError: Unexpected token -> Token(TokenType.EOF, None, position=1:21)")

    def test_R6_unexpected_token_position(self):
        self.assertEqual(self.err("PROGRAM P;\nBEGIN\n  x := ;\nEND."),
                         "ParserError: Unexpected token -> Token(TokenType.SEMI, ';', position=3:8)")

    def test_R6_keyword_repr_uppercase(self):
        self.assertEqual(self.err("program p; begin begin end; end. begin"),
                         "ParserError: Unexpected token -> Token(TokenType.BEGIN, 'BEGIN', position=1:34)")

    def test_R6_number_repr(self):
        self.assertIn("Token(TokenType.REAL_CONST, 3.14,", self.err("PROGRAM P; BEGIN x 3.14 END."))
        self.assertIn("Token(TokenType.INTEGER_CONST, 5,", self.err("PROGRAM P; BEGIN x := 1 5 END."))

    def test_R6_call_requires_parens(self):
        self.assertIn("TokenType.END", self.err(prog("P")))

    def test_R6_empty_var_section(self):
        self.assertIn("TokenType.BEGIN", self.err("PROGRAM P; VAR BEGIN END."))

    def test_R6_trailing_tokens_after_dot(self):
        self.assertIn("TokenType.ID", self.err("PROGRAM P; BEGIN END. x"))

    def test_R6_missing_type(self):
        self.err("PROGRAM P; VAR a : ; BEGIN END.")

    def test_R6_lazy_lexing_parser_error_first(self):
        self.assertIn("ParserError", self.err("PROGRAM P; BEGIN ; ; END END $"))

    def test_R3_lexer_error_through_parser(self):
        self.assertIn("LexerError", self.err("PROGRAM P; BEGIN # END.", LexerError))


if __name__ == "__main__":
    unittest.main()
