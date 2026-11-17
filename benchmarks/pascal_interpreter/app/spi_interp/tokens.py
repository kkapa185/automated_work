from enum import Enum


class TokenType(Enum):
    PLUS = "+"
    MINUS = "-"
    MUL = "*"
    FLOAT_DIV = "/"
    LPAREN = "("
    RPAREN = ")"
    SEMI = ";"
    DOT = "."
    COLON = ":"
    COMMA = ","
    PROGRAM = "PROGRAM"
    INTEGER = "INTEGER"
    REAL = "REAL"
    INTEGER_DIV = "DIV"
    VAR = "VAR"
    PROCEDURE = "PROCEDURE"
    BEGIN = "BEGIN"
    END = "END"
    ID = "ID"
    INTEGER_CONST = "INTEGER_CONST"
    REAL_CONST = "REAL_CONST"
    ASSIGN = ":="
    EOF = "EOF"


RESERVED_KEYWORDS = {
    t.value: t
    for t in (TokenType.PROGRAM, TokenType.INTEGER, TokenType.REAL, TokenType.INTEGER_DIV,
              TokenType.VAR, TokenType.PROCEDURE, TokenType.BEGIN, TokenType.END)
}


class Token:
    def __init__(self, type, value, line=1, column=1):
        self.type = type
        self.value = value
        self.line = line
        self.column = column

    def __str__(self):
        return (f"Token(TokenType.{self.type.name}, {self.value!r}, "
                f"position={self.line}:{self.column})")

    __repr__ = __str__
