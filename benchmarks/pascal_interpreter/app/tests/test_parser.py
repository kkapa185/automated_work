import unittest
from helpers import *  # noqa
from spi_interp.lexer import Lexer
from spi_interp.parser import Parser, ParserError
from spi_interp import ast_nodes as A


def parse(s):
    return Parser(Lexer(s)).parse()


def err(s):
    with unittest.TestCase().assertRaises(ParserError) as c:
        parse(s)
    return str(c.exception)


class ParserTests(unittest.TestCase):
    def test_r5_minimal(self):
        p = parse("PROGRAM P; BEGIN END.")
        self.assertEqual(p.name, 'P')
        self.assertIsInstance(p.block.compound.children[0], A.NoOp)

    def test_r5_declarations_grouped(self):
        p = parse("program p; var a, b : integer; x : real; begin end.")
        self.assertEqual([d.var_node.value for d in p.block.declarations], ['a', 'b', 'x'])
        self.assertEqual([d.type_node.value for d in p.block.declarations],
                         ['INTEGER', 'INTEGER', 'REAL'])

    def test_r5_procedure_params(self):
        p = parse("PROGRAM p; PROCEDURE Q(a, b : INTEGER; c : REAL); BEGIN END; BEGIN Q(1,2,3.0) END.")
        q = p.block.declarations[0]
        self.assertEqual([x.var_node.value for x in q.params], ['a', 'b', 'c'])
        call = p.block.compound.children[0]
        self.assertIsInstance(call, A.ProcedureCall)
        self.assertEqual(len(call.args), 3)

    def test_r5_procedure_without_params_and_empty_call(self):
        p = parse("PROGRAM p; PROCEDURE Q; BEGIN END; BEGIN Q() END.")
        self.assertEqual(p.block.declarations[0].params, [])
        self.assertEqual(p.block.compound.children[0].args, [])

    def test_r5_nested_procedures(self):
        p = parse("PROGRAM p; PROCEDURE A; PROCEDURE B; BEGIN END; BEGIN B() END; BEGIN A() END.")
        self.assertEqual(p.block.declarations[0].block.declarations[0].name, 'B')

    def test_r5_empty_statements(self):
        p = parse("PROGRAM p; VAR x:INTEGER; BEGIN ;; x := 1;; END.")
        kinds = [type(c).__name__ for c in p.block.compound.children]
        self.assertEqual(kinds, ['NoOp', 'NoOp', 'Assign', 'NoOp', 'NoOp'])

    def test_r5_precedence(self):
        p = parse("PROGRAM p; VAR x:INTEGER; BEGIN x := 1 + 2 * 3 - -4 END.")
        e = p.block.compound.children[0].right
        self.assertEqual(e.op.value, '-')
        self.assertEqual(e.left.op.value, '+')
        self.assertEqual(e.left.right.op.value, '*')
        self.assertIsInstance(e.right, A.UnaryOp)

    def test_r5_left_assoc(self):
        e = parse("PROGRAM p; VAR x:INTEGER; BEGIN x := 8 DIV 2 / 2 END.").block.compound.children[0].right
        self.assertEqual(e.op.value, '/')
        self.assertEqual(e.left.op.value, 'DIV')

    def test_r5_second_var_is_error(self):
        self.assertEqual(
            err("PROGRAM p;\nVAR a : INTEGER;\nVAR b : INTEGER;\nBEGIN END."),
            "ParserError: Unexpected token -> Token(TokenType.VAR, 'VAR', position=3:1)")

    def test_r5_var_after_procedure_is_error(self):
        m = err("PROGRAM p; PROCEDURE Q; BEGIN END; VAR b : INTEGER; BEGIN END.")
        self.assertIn("TokenType.VAR", m)

    def test_r5_var_requires_declaration(self):
        self.assertIn("TokenType.BEGIN", err("PROGRAM p; VAR BEGIN END."))

    def test_r6_missing_dot_reports_eof(self):
        self.assertEqual(err("PROGRAM p; BEGIN END"),
                         "ParserError: Unexpected token -> Token(TokenType.EOF, None, position=1:21)")

    def test_r6_missing_semi(self):
        self.assertEqual(err("PROGRAM p\nBEGIN END."),
                         "ParserError: Unexpected token -> Token(TokenType.BEGIN, 'BEGIN', position=2:1)")

    def test_r6_assignment_missing_expr(self):
        self.assertIn("TokenType.END, 'END'", err("PROGRAM p; VAR x:INTEGER; BEGIN x := END."))

    def test_r6_call_requires_parens(self):
        self.assertIn("TokenType.END", err("PROGRAM p; PROCEDURE Q; BEGIN END; BEGIN Q END."))

    def test_r6_trailing_garbage(self):
        self.assertIn("TokenType.ID, 'x'", err("PROGRAM p; BEGIN END. x"))

    def test_r6_number_value_repr(self):
        self.assertIn("TokenType.REAL_CONST, 3.14,", err("PROGRAM p; VAR x : 3.14; BEGIN END."))


if __name__ == '__main__':
    unittest.main()
