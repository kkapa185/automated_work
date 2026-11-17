"""Encoding helpers."""
from __future__ import annotations

import base64
import binascii
import struct

from .exc import BadData


def want_bytes(s: str | bytes, encoding: str = "utf-8", errors: str = "strict") -> bytes:
    """Return ``s`` as bytes, encoding str values."""
    if isinstance(s, str):
        return s.encode(encoding, errors)
    return s


def base64_encode(string: str | bytes) -> bytes:
    """URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(want_bytes(string)).rstrip(b"=")


def base64_decode(string: str | bytes) -> bytes:
    """Decode unpadded URL-safe base64; raise :class:`BadData` if invalid."""
    try:
        data = want_bytes(string, encoding="ascii", errors="strict")
    except UnicodeEncodeError as e:
        raise BadData("Invalid base64-encoded data") from e
    data += b"=" * (-len(data) % 4)
    try:
        return base64.b64decode(data, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as e:
        raise BadData("Invalid base64-encoded data") from e


_int64_struct = struct.Struct(">Q")


def int_to_bytes(num: int) -> bytes:
    """Minimal-length big-endian bytes of a non-negative int."""
    return num.to_bytes((num.bit_length() + 7) // 8, "big")


def bytes_to_int(bytestr: bytes) -> int:
    return int.from_bytes(bytestr, "big")
