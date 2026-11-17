"""Exceptions raised when signatures or payloads are invalid."""

class BadData(Exception):
    """Raised if bad data of any sort was encountered. Base of all others."""

    message = None

    def __init__(self, message):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return self.message


class BadSignature(BadData):
    """Raised if a signature does not match."""

    payload = None
    """The payload that failed the signature test (unverified, be careful)."""

    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload


class BadTimeSignature(BadSignature):
    """Raised if a timestamp is invalid or the signature does not match."""

    date_signed = None
    """If the signature has a timestamp, the datetime it was signed."""

    def __init__(self, message, payload=None, date_signed=None):
        super().__init__(message, payload)
        self.date_signed = date_signed


class SignatureExpired(BadTimeSignature):
    """Raised if a signature timestamp is older than ``max_age``."""


class BadHeader(BadSignature):
    """Raised if a signed header is invalid in some form."""

    header = None
    original_error = None

    def __init__(self, message, payload=None, header=None, original_error=None):
        super().__init__(message, payload)
        self.header = header
        self.original_error = original_error


class BadPayload(BadData):
    """Raised if a payload is invalid (e.g. it could not be unserialized)."""

    original_error = None

    def __init__(self, message, original_error=None):
        super().__init__(message)
        self.original_error = original_error
