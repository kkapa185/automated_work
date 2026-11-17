import os
import unittest
from helpers import *  # noqa
import subprocess

EX = os.path.join(ROOT, 'examples', 'nested.pas')


class CliTests(unittest.TestCase):
    def test_r1_success_silent(self):
        p = cli("PROGRAM Main; VAR x : INTEGER; BEGIN x := 1 END.")
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_r9_stack_flag_example_file(self):
        p = subprocess.run([os.path.join(ROOT, 'spi'), EX, '--stack'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertTrue(p.stdout.startswith("ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\n"))
        self.assertTrue(p.stdout.endswith("LEAVE: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n"
                                          + line('a', 4) + "\n\n"))

    def test_r10_scope_flag_and_combined(self):
        p = subprocess.run([os.path.join(ROOT, 'spi'), '--stack', EX, '--scope'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn("ENTER scope: global", p.stdout)
        self.assertIn("ENTER: PROGRAM Main", p.stdout)
        self.assertLess(p.stdout.index("LEAVE scope: global"), p.stdout.index("ENTER: PROGRAM"))

    def test_r4_lexer_error(self):
        p = cli("PROGRAM Main;\nBEGIN\n  ? \nEND.")
        self.assertEqual((p.returncode, p.stdout),
                         (1, "LexerError: Lexer error on '?' line: 3 column: 3\n"))

    def test_r6_parser_error(self):
        p = cli("PROGRAM Main;\nVAR a : INTEGER;\nVAR b : INTEGER;\nBEGIN END.")
        self.assertEqual((p.returncode, p.stdout), (
            1, "ParserError: Unexpected token -> Token(TokenType.VAR, 'VAR', position=3:1)\n"))

    def test_r7_semantic_errors(self):
        p = cli("PROGRAM Main;\nVAR a, a : INTEGER;\nBEGIN END.")
        self.assertEqual((p.returncode, p.stdout), (
            1, "SemanticError: Duplicate id found -> Token(TokenType.ID, 'a', position=2:8)\n"))
        p = cli("PROGRAM Main;\nBEGIN\n  b := 1\nEND.", "--stack")
        self.assertEqual((p.returncode, p.stdout), (
            1, "SemanticError: Identifier not found -> Token(TokenType.ID, 'b', position=3:3)\n"))

    def test_r12_runtime_error(self):
        p = cli("PROGRAM Main; VAR x : REAL; BEGIN x := 1 / 0 END.")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(p.stdout.startswith("RuntimeError:"))

    def test_r11_usage_and_missing_file(self):
        exe = os.path.join(ROOT, 'spi')
        self.assertEqual(subprocess.run([exe], capture_output=True).returncode, 2)
        self.assertEqual(subprocess.run([exe, '/no/such.pas'], capture_output=True).returncode, 2)
        self.assertEqual(subprocess.run([exe, EX, '--bogus'], capture_output=True).returncode, 2)


if __name__ == '__main__':
    unittest.main()
