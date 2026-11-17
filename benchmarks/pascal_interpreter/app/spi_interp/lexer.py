"""Lexer: turns source text into tokens."""
from enum import Enum


class TokenType(Enum):
    PLUS = '+'
    MINUS = '-'
    MUL = '*'
    FLOAT_DIV = '/'
    LPAREN = '('
    RPAREN = ')'
    SEMI = ';'
    DOT = '.'
    COLON = ':'
    COMMA = ','
    PROGRAM = 'PROGRAM'
    INTEGER = 'INTEGER'
    REAL = 'REAL'
    INTEGER_DIV = 'DIV'
    VAR = 'VAR'
    PROCEDURE = 'PROCEDURE'
    BEGIN = 'BEGIN'
    END = 'END'
    ID = 'ID'
    INTEGER_CONST = 'INTEGER_CONST'
    REAL_CONST = 'REAL_CONST'
    ASSIGN = ':='
    EOF = 'EOF'


RESERVED = {
    'PROGRAM': TokenType.PROGRAM,
    'INTEGER': TokenType.INTEGER,
    'REAL': TokenType.REAL,
    'DIV': TokenType.INTEGER_DIV,
    'VAR': TokenType.VAR,
    'PROCEDURE': TokenType.PROCEDURE,
    'BEGIN': TokenType.BEGIN,
    'END': TokenType.END,
}

SINGLE = {
    '+': TokenType.PLUS, '-': TokenType.MINUS, '*': TokenType.MUL,
    '/': TokenType.FLOAT_DIV, '(': TokenType.LPAREN, ')': TokenType.RPAREN,
    ';': TokenType.SEMI, '.': TokenType.DOT, ',': TokenType.COMMA,
}


class LexerError(Exception):
    def __init__(self, char, line, column):
        self.char, self.line, self.column = char, line, column
        super().__init__(
            f"LexerError: Lexer error on '{char}' line: {line} column: {column}")


class Token:
    def __init__(self, type, value, line=None, column=None):
        self.type = type
        self.value = value
        self.line = line
        self.column = column

    def __str__(self):
        return (f"Token(TokenType.{self.type.name}, {self.value!r}, "
                f"position={self.line}:{self.column})")

    __repr__ = __str__


class Lexer:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1

    def _cur(self):
        return self.text[self.pos] if self.pos < len(self.text) else None

    def _peek(self):
        p = self.pos + 1
        return self.text[p] if p < len(self.text) else None

    def _advance(self):
        if self.text[self.pos] == '\n':
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        self.pos += 1

    def _skip_comment(self):
        line, col = self.line, self.column
        self._advance()  # '{'
        while self._cur() is not None and self._cur() != '}':
            self._advance()
        if self._cur() is None:
            raise LexerError('{', line, col)
        self._advance()

    def _number(self):
        line, col = self.line, self.column
        s = ''
        while self._cur() is not None and self._cur().isascii() and self._cur().isdigit():
            s += self._cur()
            self._advance()
        nxt = self._peek()
        if self._cur() == '.' and nxt is not None and nxt.isascii() and nxt.isdigit():
            s += '.'
            self._advance()
            while self._cur() is not None and self._cur().isascii() and self._cur().isdigit():
                s += self._cur()
                self._advance()
            return Token(TokenType.REAL_CONST, float(s), line, col)
        return Token(TokenType.INTEGER_CONST, int(s), line, col)

    def _id(self):
        line, col = self.line, self.column
        s = ''
        while self._cur() is not None and self._cur().isascii() and self._cur().isalnum():
            s += self._cur()
            self._advance()
        t = RESERVED.get(s.upper())
        if t is not None:
            return Token(t, s.upper(), line, col)
        return Token(TokenType.ID, s, line, col)

    def get_next_token(self):
        while self._cur() is not None:
            c = self._cur()
            if c in ' \t\r\n\f\v':
                self._advance()
            elif c == '{':
                self._skip_comment()
            elif c.isascii() and c.isalpha():
                return self._id()
            elif c.isascii() and c.isdigit():
                return self._number()
            elif c == ':' and self._peek() == '=':
                tok = Token(TokenType.ASSIGN, ':=', self.line, self.column)
                self._advance()
                self._advance()
                return tok
            elif c == ':':
                tok = Token(TokenType.COLON, ':', self.line, self.column)
                self._advance()
                return tok
            elif c in SINGLE:
                tok = Token(SINGLE[c], c, self.line, self.column)
                self._advance()
                return tok
            else:
                raise LexerError(c, self.line, self.column)
        return Token(TokenType.EOF, None, self.line, self.column)

    def tokens(self):
        out = []
        while True:
            t = self.get_next_token()
            out.append(t)
            if t.type is TokenType.EOF:
                return out
