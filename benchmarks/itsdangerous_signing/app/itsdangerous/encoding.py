"""Encoding helpers: bytes coercion and URL-safe base64 without padding."""
import base64

from .exc import BadData


def want_bytes(s, encoding="utf-8", errors="strict"):
    """Return ``s`` as bytes, encoding it if it is a ``str``."""
    if isinstance(s, str):
        s = s.encode(encoding, errors)
    return s


def base64_encode(string):
    """URL-safe base64 encode a ``str`` or ``bytes``, stripping ``=`` padding.

    Returns ``bytes``.
    """
    string = want_bytes(string)
    return base64.urlsafe_b64encode(string).rstrip(b"=")


def base64_decode(string):
    """Decode URL-safe base64 (padding optional) from ``str`` or ``bytes``.

    Raises :exc:`~itsdangerous.exc.BadData` if the input is not valid.
    """
    string = want_bytes(string, encoding="ascii", errors="ignore")
    string += b"=" * (-len(string) % 4)
    try:
        return base64.urlsafe_b64decode(string)
    except (TypeError, ValueError) as e:
        raise BadData("Invalid base64-encoded data") from e


def int_to_bytes(num):
    """Big-endian minimal-length encoding of a non-negative int (0 -> b"")."""
    return num.to_bytes((num.bit_length() + 7) // 8, "big")


def bytes_to_int(data):
    return int.from_bytes(data, "big")
