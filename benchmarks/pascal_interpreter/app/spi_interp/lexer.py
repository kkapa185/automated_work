from .errors import LexerError
from .tokens import RESERVED_KEYWORDS, Token, TokenType

_SINGLE = {
    "+": TokenType.PLUS, "-": TokenType.MINUS, "*": TokenType.MUL,
    "/": TokenType.FLOAT_DIV, "(": TokenType.LPAREN, ")": TokenType.RPAREN,
    ";": TokenType.SEMI, ".": TokenType.DOT, ",": TokenType.COMMA,
}


class Lexer:
    """Pull-based lexer: errors surface only when the parser reaches them."""

    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1

    def _peek(self, n=1):
        p = self.pos + n
        return self.text[p] if p < len(self.text) else None

    def _advance(self):
        ch = self.text[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1

    @property
    def _cur(self):
        return self.text[self.pos] if self.pos < len(self.text) else None

    def _skip_ws_and_comments(self):
        while self._cur is not None:
            if self._cur.isspace():
                self._advance()
            elif self._cur == "{":
                line, col = self.line, self.column
                while self._cur is not None and self._cur != "}":
                    self._advance()
                if self._cur is None:
                    raise LexerError("{", line, col)
                self._advance()
            else:
                break

    @staticmethod
    def _is_digit(c):
        return c is not None and c in "0123456789"

    @staticmethod
    def _is_alpha(c):
        return c is not None and c.isascii() and c.isalpha()

    def _number(self, line, col):
        s = ""
        while self._is_digit(self._cur):
            s += self._cur
            self._advance()
        if self._cur == "." and self._is_digit(self._peek()):
            s += "."
            self._advance()
            while self._is_digit(self._cur):
                s += self._cur
                self._advance()
            return Token(TokenType.REAL_CONST, float(s), line, col)
        return Token(TokenType.INTEGER_CONST, int(s), line, col)

    def _identifier(self, line, col):
        s = ""
        while self._is_alpha(self._cur) or self._is_digit(self._cur):
            s += self._cur
            self._advance()
        ttype = RESERVED_KEYWORDS.get(s.upper())
        if ttype is not None:
            return Token(ttype, s.upper(), line, col)
        return Token(TokenType.ID, s, line, col)

    def get_next_token(self):
        self._skip_ws_and_comments()
        c = self._cur
        line, col = self.line, self.column
        if c is None:
            return Token(TokenType.EOF, None, line, col)
        if self._is_alpha(c):
            return self._identifier(line, col)
        if self._is_digit(c):
            return self._number(line, col)
        if c == ":" and self._peek() == "=":
            self._advance()
            self._advance()
            return Token(TokenType.ASSIGN, ":=", line, col)
        if c == ":":
            self._advance()
            return Token(TokenType.COLON, ":", line, col)
        if c in _SINGLE:
            self._advance()
            return Token(_SINGLE[c], c, line, col)
        raise LexerError(c, line, col)

    def tokens(self):
        while True:
            t = self.get_next_token()
            yield t
            if t.type is TokenType.EOF:
                return
