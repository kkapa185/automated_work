import os
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import ROOT

SPI = os.path.join(ROOT, "spi")
GOOD = "PROGRAM Main;\nVAR a : INTEGER;\nBEGIN a := 2 END.\n"


def cli(src, *flags, name="t.pas"):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write(src)
        return subprocess.run([sys.executable, SPI, p, *flags], capture_output=True, text=True)


class CliTests(unittest.TestCase):
    def test_R1_success_silent(self):
        r = cli(GOOD)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_R1_executable_directly(self):
        self.assertTrue(os.access(SPI, os.X_OK))

    def test_R1_usage_errors(self):
        r = subprocess.run([sys.executable, SPI], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr)
        r = subprocess.run([sys.executable, SPI, "/no/such/file.pas"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        r = cli(GOOD, "--bogus")
        self.assertEqual(r.returncode, 2)

    def test_R3_lexer_error(self):
        r = cli("PROGRAM Main;\nBEGIN\n  a := 1 ? 2\nEND.\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "LexerError: Lexer error on '?' line: 3 column: 10\n")

    def test_R6_parser_error(self):
        r = cli("PROGRAM Main;\nBEGIN\nEND\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "ParserError: Unexpected token -> Token(TokenType.EOF, None, position=4:1)\n")

    def test_R7_semantic_errors(self):
        r = cli("PROGRAM Main;\nVAR a : INTEGER;\n    a : INTEGER;\nBEGIN END.\n")
        self.assertEqual((r.returncode, r.stdout),
                         (1, "SemanticError: Duplicate id found -> Token(TokenType.ID, 'a', position=3:5)\n"))
        r = cli("PROGRAM Main;\nBEGIN\n  b := 1\nEND.\n")
        self.assertEqual((r.returncode, r.stdout),
                         (1, "SemanticError: Identifier not found -> Token(TokenType.ID, 'b', position=3:3)\n"))

    def test_R12_semantic_error_blocks_execution_output(self):
        r = cli("PROGRAM Main;\nBEGIN\n  b := 1\nEND.\n", "--stack")
        self.assertNotIn("ENTER", r.stdout)

    def test_R10_stack_flag(self):
        r = cli(GOOD, "--stack")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout,
                         "ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n"
                         "LEAVE: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n"
                         "   a                   : 2\n\n")

    def test_R11_scope_flag_and_combination(self):
        r = cli(GOOD, "--stack", "--scope")
        self.assertEqual(r.returncode, 0)
        self.assertIn("ENTER scope: global", r.stdout)
        self.assertIn("ENTER: PROGRAM Main", r.stdout)
        self.assertLess(r.stdout.index("LEAVE scope: global"), r.stdout.index("ENTER: PROGRAM"))
        r2 = cli(GOOD, "--scope")
        self.assertNotIn("CALL STACK", r2.stdout)

    def test_R12_runtime_error(self):
        r = cli("PROGRAM Main; VAR a : INTEGER; BEGIN a := 1 DIV 0 END.")
        self.assertEqual((r.returncode, r.stdout), (1, "RuntimeError: Division by zero\n"))

    def test_R12_overflow_and_deep_nesting(self):
        r = cli("PROGRAM M; VAR a : REAL; BEGIN a := 1" + " * 10" * 400 + " / 1 END.")
        self.assertEqual((r.returncode, r.stdout), (1, "RuntimeError: Numeric overflow\n"))
        r = cli("PROGRAM M; VAR a : REAL; BEGIN a := " + "(" * 3000 + "1" + ")" * 3000 + " END.")
        self.assertEqual(r.returncode, 1)
        self.assertIn("RuntimeError", r.stdout)

    def test_example_program(self):
        r = subprocess.run([sys.executable, SPI, os.path.join(ROOT, "examples", "nested.pas"), "--stack"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("3: PROCEDURE Beta", r.stdout)


if __name__ == "__main__":
    unittest.main()
