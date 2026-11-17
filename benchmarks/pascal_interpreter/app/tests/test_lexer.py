import unittest
from helpers import *  # noqa
from spi_interp.lexer import Lexer, LexerError, TokenType as T


def toks(s):
    return Lexer(s).tokens()


class LexerTests(unittest.TestCase):
    def test_r2_keywords_case_insensitive_uppercased(self):
        t = toks("begin Begin BEGIN div Var procedure program integer real end")
        self.assertEqual([x.type for x in t[:-1]], [
            T.BEGIN, T.BEGIN, T.BEGIN, T.INTEGER_DIV, T.VAR, T.PROCEDURE,
            T.PROGRAM, T.INTEGER, T.REAL, T.END])
        self.assertEqual([x.value for x in t[:3]], ['BEGIN'] * 3)

    def test_r2_identifiers_case_sensitive(self):
        t = toks("abc Abc a1b2")
        self.assertEqual([(x.type, x.value) for x in t[:-1]],
                         [(T.ID, 'abc'), (T.ID, 'Abc'), (T.ID, 'a1b2')])

    def test_r2_numbers(self):
        t = toks("5 3.14 007")
        self.assertEqual([(x.type, x.value) for x in t[:-1]],
                         [(T.INTEGER_CONST, 5), (T.REAL_CONST, 3.14), (T.INTEGER_CONST, 7)])

    def test_r2_symbols(self):
        t = toks("+ - * / ( ) ; . : , :=")
        self.assertEqual([x.type for x in t[:-1]], [
            T.PLUS, T.MINUS, T.MUL, T.FLOAT_DIV, T.LPAREN, T.RPAREN, T.SEMI,
            T.DOT, T.COLON, T.COMMA, T.ASSIGN])

    def test_r2_comments_and_whitespace(self):
        t = toks("a {comment\n spanning } b\t\n  c")
        self.assertEqual([x.value for x in t[:-1]], ['a', 'b', 'c'])

    def test_r2_number_then_dot(self):
        t = toks("3.")
        self.assertEqual([x.type for x in t], [T.INTEGER_CONST, T.DOT, T.EOF])

    def test_r3_positions_and_repr(self):
        t = toks("BEGIN\n  x := 5")
        self.assertEqual(str(t[0]), "Token(TokenType.BEGIN, 'BEGIN', position=1:1)")
        self.assertEqual(str(t[1]), "Token(TokenType.ID, 'x', position=2:3)")
        self.assertEqual(str(t[2]), "Token(TokenType.ASSIGN, ':=', position=2:5)")
        self.assertEqual(str(t[3]), "Token(TokenType.INTEGER_CONST, 5, position=2:8)")
        self.assertEqual(str(toks("3.14")[0]),
                         "Token(TokenType.REAL_CONST, 3.14, position=1:1)")

    def test_r3_position_after_comment(self):
        t = toks("{ab}\n{c} x")
        self.assertEqual((t[0].line, t[0].column), (2, 5))

    def test_r3_eof(self):
        self.assertEqual(toks("")[0].type, T.EOF)

    def test_r4_lexer_error(self):
        with self.assertRaises(LexerError) as c:
            toks("a\n  $")
        self.assertEqual(str(c.exception), "LexerError: Lexer error on '$' line: 2 column: 3")

    def test_r4_underscore_invalid(self):
        with self.assertRaises(LexerError):
            toks("a_b")

    def test_r4_unterminated_comment(self):
        with self.assertRaises(LexerError):
            toks("x { never closed")


if __name__ == '__main__':
    unittest.main()
