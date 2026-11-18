class SqlError(Exception):
    """An SQL error. kind is 'parse' (detected while preparing a statement)
    or 'runtime' (detected while stepping it)."""

    def __init__(self, msg, kind='runtime'):
        Exception.__init__(self, msg)
        self.msg = msg
        self.kind = kind


def parse_error(msg):
    return SqlError(msg, 'parse')


class RaiseIgnore(Exception):
    """RAISE(IGNORE) inside a trigger program."""
