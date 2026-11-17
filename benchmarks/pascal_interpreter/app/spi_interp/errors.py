class SpiError(Exception):
    """Base class; str(error) is the exact message printed by the CLI."""


class LexerError(SpiError):
    def __init__(self, char, line, column):
        super().__init__(f"LexerError: Lexer error on '{char}' line: {line} column: {column}")


class ParserError(SpiError):
    def __init__(self, token):
        super().__init__(f"ParserError: Unexpected token -> {token}")
        self.token = token


class SemanticError(SpiError):
    def __init__(self, message, token):
        super().__init__(f"SemanticError: {message} -> {token}")
        self.token = token


class SpiRuntimeError(SpiError):
    def __init__(self, message):
        super().__init__(f"RuntimeError: {message}")
