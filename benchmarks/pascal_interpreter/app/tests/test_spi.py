import io
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import spi  # noqa: E402
from spi import (Lexer, Parser, TokenType, LexerError, ParserError, SemanticError,  # noqa: E402
                 InterpreterError, SemanticAnalyzer, run_source)

SPI = os.path.join(ROOT, 'spi')


def toks(text):
    lx = Lexer(text)
    out = []
    while True:
        t = lx.next_token()
        out.append(t)
        if t.type == TokenType.EOF:
            return out


def run(text, **kw):
    buf = io.StringIO()
    run_source(text, out=buf, **kw)
    return buf.getvalue()


def err(text):
    try:
        run(text)
    except spi.SpiError as e:
        return str(e)
    raise AssertionError("no error")


class LexerTests(unittest.TestCase):
    def test_R2_keywords_case_insensitive(self):
        t = toks("pRoGrAm begin End div var procedure integer real")
        self.assertEqual([x.type for x in t[:-1]], [
            TokenType.PROGRAM, TokenType.BEGIN, TokenType.END, TokenType.INTEGER_DIV, TokenType.VAR,
            TokenType.PROCEDURE, TokenType.INTEGER, TokenType.REAL])
        self.assertEqual(t[0].value, 'PROGRAM')

    def test_R2_identifiers_case_sensitive(self):
        t = toks("abc ABC a1B2")
        self.assertEqual([x.value for x in t[:-1]], ['abc', 'ABC', 'a1B2'])
        self.assertTrue(all(x.type == TokenType.ID for x in t[:-1]))

    def test_R2_numbers_and_ops(self):
        t = toks("3 3.14 + - * / ( ) ; . : , :=")
        self.assertEqual([x.type for x in t], [
            TokenType.INTEGER_CONST, TokenType.REAL_CONST, TokenType.PLUS, TokenType.MINUS, TokenType.MUL,
            TokenType.FLOAT_DIV, TokenType.LPAREN, TokenType.RPAREN, TokenType.SEMI, TokenType.DOT,
            TokenType.COLON, TokenType.COMMA, TokenType.ASSIGN, TokenType.EOF])
        self.assertEqual(t[0].value, 3)
        self.assertIsInstance(t[1].value, float)

    def test_R2_comments_and_positions(self):
        t = toks("{ multi\nline } x\n  y")
        self.assertEqual((t[0].line, t[0].column), (2, 8))
        self.assertEqual((t[1].line, t[1].column), (3, 3))

    def test_R2_token_str(self):
        self.assertEqual(str(toks("BEGIN")[0]), "Token(TokenType.BEGIN, 'BEGIN', position=1:1)")
        self.assertEqual(str(toks("5")[0]), "Token(TokenType.INTEGER_CONST, 5, position=1:1)")

    def test_R3_lexer_error(self):
        with self.assertRaises(LexerError) as c:
            toks("x\n  $")
        self.assertEqual(str(c.exception), "LexerError: Lexer error on '$' line: 2 column: 3")

    def test_R3_unterminated_comment(self):
        with self.assertRaises(LexerError):
            toks("{ never closed")


class ParserTests(unittest.TestCase):
    def parse(self, s):
        return Parser(Lexer(s)).parse()

    def test_R4_full_program(self):
        tree = self.parse("""program P; var a,b:integer; x:real;
            procedure Q(a, b : integer; c : real); var z: integer; begin end;
            begin ; a := 1;; Q(1, 2, 3.0); Q() end.""")
        self.assertEqual(tree.name, 'P')
        self.assertEqual(len(tree.block.declarations), 4)

    def test_R4_nested_procedures(self):
        tree = self.parse("program P; procedure A; procedure B; begin end; begin B() end; begin A() end.")
        a = tree.block.declarations[0]
        self.assertEqual(a.block.declarations[0].name, 'B')

    def test_R6_precedence_assoc(self):
        out = run("program P; var a: integer; begin a := 2 + 3 * 4 - 10 DIV 3 DIV 2 end.", show_stack=True)
        self.assertIn("a                   : 13", out.split("LEAVE")[1])

    def test_R5_unexpected_token(self):
        self.assertEqual(err("program P; begin x := ; end."),
                         "ParserError: Unexpected token -> Token(TokenType.SEMI, ';', position=1:23)")

    def test_R5_keyword_and_eof(self):
        self.assertEqual(err("program P; begin end"),
                         "ParserError: Unexpected token -> Token(TokenType.EOF, None, position=1:21)")
        self.assertEqual(err("program P;\nbegin\n  x := 5 begin\nend."),
                         "ParserError: Unexpected token -> Token(TokenType.BEGIN, 'BEGIN', position=3:10)")

    def test_R5_number_repr(self):
        self.assertEqual(err("program P; begin x 3.14 end."),
                         "ParserError: Unexpected token -> Token(TokenType.REAL_CONST, 3.14, position=1:20)")
        self.assertEqual(err("program P; var x:integer; begin x := 1 5 end."),
                         "ParserError: Unexpected token -> Token(TokenType.INTEGER_CONST, 5, position=1:40)")

    def test_R4_call_requires_parens(self):
        self.assertTrue(err("program P; procedure Q; begin end; begin Q end.").startswith("ParserError"))

    def test_R5_trailing_garbage(self):
        self.assertTrue(err("program P; begin end. x").startswith("ParserError"))


class SemanticTests(unittest.TestCase):
    def test_R7_duplicate_var(self):
        self.assertEqual(err("program P;\nvar a : integer;\n    a : real;\nbegin end."),
                         "SemanticError: Duplicate id found -> Token(TokenType.ID, 'a', position=3:5)")

    def test_R7_duplicate_param(self):
        self.assertIn("Duplicate id found -> Token(TokenType.ID, 'a'",
                      err("program P; procedure Q(a: integer; a: real); begin end; begin end."))

    def test_R7_same_name_different_scopes_ok(self):
        run("program P; var a: integer; procedure Q(a: integer); var b: integer; begin b := a end; begin a := 1 end.")

    def test_R7_undeclared_in_assignment_and_expr(self):
        self.assertEqual(err("program P; var a: integer; begin a := b end."),
                         "SemanticError: Identifier not found -> Token(TokenType.ID, 'b', position=1:39)")
        self.assertEqual(err("program P; begin\n  c := 1 end."),
                         "SemanticError: Identifier not found -> Token(TokenType.ID, 'c', position=2:3)")

    def test_R7_identifiers_case_sensitive(self):
        self.assertIn("Identifier not found", err("program P; var a: integer; begin A := 1 end."))

    def test_R7_unknown_procedure_and_arity(self):
        self.assertIn("Identifier not found", err("program P; begin Foo() end."))
        self.assertIn("Wrong number of arguments",
                      err("program P; procedure Q(a: integer); begin end; begin Q() end."))

    def test_R7_call_args_checked(self):
        self.assertIn("Identifier not found",
                      err("program P; procedure Q(a: integer); begin end; begin Q(zz) end."))

    def test_R7_symbol_tables(self):
        tree = Parser(Lexer("program P; var a: integer; procedure Q(x: real); begin end; begin end.")).parse()
        a = SemanticAnalyzer(out=io.StringIO())
        a.analyze(tree)
        self.assertIsNone(a.scope)

    def test_R10_scope_output(self):
        out = run("program P; var a: integer; procedure Q(x: real); begin end; begin end.", show_scope=True)
        self.assertIn("ENTER scope: global", out)
        self.assertIn("ENTER scope: Q", out)
        self.assertIn("LEAVE scope: Q", out)
        self.assertIn("x: <x:REAL>", out)
        self.assertIn("a: <a:INTEGER>", out)
        self.assertIn("INTEGER: INTEGER", out)


class InterpreterTests(unittest.TestCase):
    def final_members(self, src):
        out = run(src, show_stack=True)
        last = out.split("LEAVE: PROGRAM")[1]
        return [l.strip() for l in last.splitlines()[3:] if l.strip()]

    def test_R6_arithmetic(self):
        m = self.final_members("""program P; var a, b: integer; r: real;
          begin a := 7 DIV 2; b := -(-3) * +2; r := 7 / 2; end.""")
        self.assertEqual(m, ["a                   : 3", "b                   : 6", "r                   : 3.5"])

    def test_R6_real_literal_and_div(self):
        m = self.final_members("program P; var r: real; i: integer; begin r := 3.14 * 2; i := 1 / 2 + 1 end.")
        self.assertEqual(m[0], "r                   : 6.28")
        self.assertEqual(m[1], "i                   : 1.5")

    def test_R6_div_truncates_floor(self):
        m = self.final_members("program P; var a: integer; begin a := 9 DIV 4 end.")
        self.assertEqual(m, ["a                   : 2"])

    def test_R9_exact_trace_simple(self):
        out = run("program Main; begin end.", show_stack=True)
        self.assertEqual(out, "ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\n"
                              "LEAVE: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\n")

    def test_R9_trace_with_procedure(self):
        out = run("""program Main; var x: integer;
            procedure P(a, b: integer); var c: integer; begin c := a + b end;
            begin x := 2; P(x, 5) end.""", show_stack=True)
        pad = lambda n: "   %-20s: " % n
        expected = (
            "ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\n"
            "ENTER: PROCEDURE P\nCALL STACK\n2: PROCEDURE P\n" + pad('a') + "2\n" + pad('b') + "5\n"
            "1: PROGRAM Main\n" + pad('x') + "2\n\n\n"
            "LEAVE: PROCEDURE P\nCALL STACK\n2: PROCEDURE P\n" + pad('a') + "2\n" + pad('b') + "5\n"
            + pad('c') + "7\n1: PROGRAM Main\n" + pad('x') + "2\n\n\n"
            "LEAVE: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n" + pad('x') + "2\n\n\n")
        self.assertEqual(out, expected)

    def test_R9_assignment_order_and_reassign(self):
        m = self.final_members("program P; var a, b: integer; begin b := 1; a := 2; b := 3 end.")
        self.assertEqual(m, ["b                   : 3", "a                   : 2"])

    def test_R9_nested_calls_levels(self):
        out = run("""program P; procedure B; begin end;
            procedure A; begin B() end; begin A() end.""", show_stack=True)
        self.assertIn("3: PROCEDURE B\n2: PROCEDURE A\n1: PROGRAM P", out)

    def test_R9_nested_declared_procedure_call(self):
        out = run("""program P; procedure A; procedure B(n: integer); begin end; begin B(4) end;
            begin A() end.""", show_stack=True)
        self.assertIn("3: PROCEDURE B\n   n                   : 4\n2: PROCEDURE A", out)

    def test_R9_no_output_without_flag(self):
        self.assertEqual(run("program P; var a: integer; begin a := 1 end."), "")

    def test_R8_runtime_errors(self):
        self.assertIn("RuntimeError", err("program P; var a, b: integer; begin a := b end."))
        self.assertIn("RuntimeError", err("program P; var a: integer; begin a := 1 DIV 0 end."))

    def test_R8_args_evaluated_in_caller(self):
        out = run("""program P; var x: integer; procedure Q(a: integer); begin a := a * 10 end;
            begin x := 3; Q(x + 1) end.""", show_stack=True)
        self.assertIn("a                   : 40", out)
        self.assertIn("x                   : 3", out.split("LEAVE: PROCEDURE")[1])


class CLITests(unittest.TestCase):
    def cli(self, src, *flags):
        with tempfile.NamedTemporaryFile('w', suffix='.pas', delete=False) as f:
            f.write(src)
        try:
            return subprocess.run([sys.executable, SPI, f.name, *flags], capture_output=True, text=True)
        finally:
            os.unlink(f.name)

    def test_R1_success_silent(self):
        r = self.cli("program P; var a: integer; begin a := 1 end.")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_R9_stack_flag(self):
        r = self.cli("program Main; begin end.", "--stack")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\nLEAVE"))

    def test_R10_scope_flag_either_order(self):
        r = self.cli("program P; begin end.", "--stack", "--scope")
        self.assertIn("ENTER scope: global", r.stdout)
        self.assertIn("ENTER: PROGRAM P", r.stdout)

    def test_R11_errors_exit_1_on_stdout(self):
        for src, prefix in [("program P; begin $ end.", "LexerError"), ("program P; begin x end.", "ParserError"),
                            ("program P; begin x := 1 end.", "SemanticError")]:
            r = self.cli(src)
            self.assertEqual(r.returncode, 1)
            self.assertTrue(r.stdout.startswith(prefix), r.stdout)

    def test_R11_usage_and_missing_file(self):
        self.assertNotEqual(subprocess.run([sys.executable, SPI], capture_output=True).returncode, 0)
        self.assertNotEqual(subprocess.run([sys.executable, SPI, "/nonexistent.pas"],
                                           capture_output=True).returncode, 0)

    def test_R1_example_file(self):
        r = subprocess.run([sys.executable, SPI, os.path.join(ROOT, 'examples', 'nested.pas'), '--stack'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("3: PROCEDURE Beta", r.stdout)


if __name__ == '__main__':
    unittest.main()
