"""Exception hierarchy."""
from __future__ import annotations

import typing as t
from datetime import datetime


class BadData(Exception):
    """Base class for all errors raised for bad data."""

    message: str

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class BadSignature(BadData):
    """The signature does not match."""

    payload: t.Any | None

    def __init__(self, message: str, payload: t.Any | None = None) -> None:
        super().__init__(message)
        self.payload = payload


class BadTimeSignature(BadSignature):
    """Signature is valid-looking but timestamp is bad or missing."""

    date_signed: datetime | None

    def __init__(
        self,
        message: str,
        payload: t.Any | None = None,
        date_signed: datetime | None = None,
    ) -> None:
        super().__init__(message, payload)
        self.date_signed = date_signed


class SignatureExpired(BadTimeSignature):
    """Signature is valid but older than ``max_age``."""


class BadHeader(BadSignature):
    """Signature valid but the header could not be decoded."""

    header: t.Any | None
    original_error: Exception | None

    def __init__(
        self,
        message: str,
        payload: t.Any | None = None,
        header: t.Any | None = None,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message, payload)
        self.header = header
        self.original_error = original_error


class BadPayload(BadData):
    """The payload could not be decoded or deserialized."""

    original_error: Exception | None

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error
