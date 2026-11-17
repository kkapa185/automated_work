"""Encoding helpers."""
from __future__ import annotations

import base64
import binascii
import typing as t

from .exc import BadData


def want_bytes(s: str | bytes, encoding: str = "utf-8", errors: str = "strict") -> bytes:
    """Return ``s`` as bytes, encoding str values."""
    if isinstance(s, str):
        return s.encode(encoding, errors)
    return s


def base64_encode(string: str | bytes) -> bytes:
    """URL-safe base64 encode, with padding stripped."""
    return base64.urlsafe_b64encode(want_bytes(string)).rstrip(b"=")


def base64_decode(string: str | bytes) -> bytes:
    """Decode URL-safe base64 that may lack padding; raise BadData if invalid."""
    raw = want_bytes(string, "ascii", "ignore") if isinstance(string, str) else string
    raw = raw + b"=" * (-len(raw) % 4)
    try:
        return base64.b64decode(raw, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, TypeError) as e:
        raise BadData("Invalid base64-encoded data") from e


def int_to_bytes(num: int) -> bytes:
    """Minimal-length big-endian encoding (b"" for 0)."""
    return num.to_bytes((num.bit_length() + 7) // 8, "big")


def bytes_to_int(data: bytes) -> int:
    return int.from_bytes(data, "big")


_ = t  # keep typing import for annotations
