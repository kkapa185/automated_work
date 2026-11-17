import unittest

from tests.helpers import ROOT  # noqa: F401
from spi_interp.errors import LexerError
from spi_interp.lexer import Lexer
from spi_interp.tokens import TokenType as T


def toks(s):
    return list(Lexer(s).tokens())


class LexerTests(unittest.TestCase):
    def test_R2_symbols(self):
        types = [t.type for t in toks("+ - * / ( ) ; . : , :=")]
        self.assertEqual(types, [T.PLUS, T.MINUS, T.MUL, T.FLOAT_DIV, T.LPAREN, T.RPAREN,
                                 T.SEMI, T.DOT, T.COLON, T.COMMA, T.ASSIGN, T.EOF])

    def test_R2_keywords_case_insensitive_uppercased(self):
        ts = toks("begin Begin END div pRoGrAm var procedure integer real")
        self.assertEqual([t.value for t in ts[:-1]], ["BEGIN", "BEGIN", "END", "DIV", "PROGRAM",
                                                      "VAR", "PROCEDURE", "INTEGER", "REAL"])
        self.assertEqual(ts[3].type, T.INTEGER_DIV)

    def test_R2_identifiers_case_sensitive(self):
        ts = toks("abc ABC a1B2")
        self.assertEqual([(t.type, t.value) for t in ts[:3]], [(T.ID, "abc"), (T.ID, "ABC"), (T.ID, "a1B2")])

    def test_R2_numbers(self):
        ts = toks("5 3.14 007")
        self.assertEqual([(t.type, t.value) for t in ts[:3]],
                         [(T.INTEGER_CONST, 5), (T.REAL_CONST, 3.14), (T.INTEGER_CONST, 7)])

    def test_R2_integer_then_dot(self):
        self.assertEqual([t.type for t in toks("5.")], [T.INTEGER_CONST, T.DOT, T.EOF])

    def test_R2_comments_and_whitespace(self):
        ts = toks("a {comment\n over lines} b\t\n c")
        self.assertEqual([t.value for t in ts[:-1]], ["a", "b", "c"])

    def test_R4_positions_and_repr(self):
        ts = toks("ab\n  :=  begin")
        self.assertEqual(str(ts[0]), "Token(TokenType.ID, 'ab', position=1:1)")
        self.assertEqual(str(ts[1]), "Token(TokenType.ASSIGN, ':=', position=2:3)")
        self.assertEqual(str(ts[2]), "Token(TokenType.BEGIN, 'BEGIN', position=2:7)")
        self.assertEqual(str(toks("3.14")[0]), "Token(TokenType.REAL_CONST, 3.14, position=1:1)")
        self.assertEqual(str(toks("5")[0]), "Token(TokenType.INTEGER_CONST, 5, position=1:1)")
        self.assertEqual(str(toks("")[0]), "Token(TokenType.EOF, None, position=1:1)")

    def test_R3_lexer_error(self):
        with self.assertRaises(LexerError) as c:
            toks("a\n  b $")
        self.assertEqual(str(c.exception), "LexerError: Lexer error on '$' line: 2 column: 5")

    def test_R3_unterminated_comment(self):
        with self.assertRaises(LexerError):
            toks("x { never closed")


if __name__ == "__main__":
    unittest.main()
