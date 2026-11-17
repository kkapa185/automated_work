"""URL-safe serializers (compressed + base64)."""
from __future__ import annotations

import typing as t
import zlib

from .encoding import base64_decode, base64_encode
from .exc import BadPayload
from .serializer import Serializer, TimedSerializer


class URLSafeSerializerMixin:
    def load_payload(self, payload: bytes, *args: t.Any, **kwargs: t.Any) -> t.Any:  # type: ignore[override]
        decompress = False
        if payload.startswith(b"."):
            payload = payload[1:]
            decompress = True
        try:
            json = base64_decode(payload)
        except Exception as e:
            raise BadPayload(
                "Could not base64 decode the payload because of an exception", original_error=e
            ) from e
        if decompress:
            try:
                json = zlib.decompress(json)
            except Exception as e:
                raise BadPayload(
                    "Could not zlib decompress the payload before decoding the payload",
                    original_error=e,
                ) from e
        return super().load_payload(json, *args, **kwargs)  # type: ignore[misc]

    def dump_payload(self, obj: t.Any) -> bytes:  # type: ignore[override]
        json = super().dump_payload(obj)  # type: ignore[misc]
        is_compressed = False
        compressed = zlib.compress(json)
        # the "." prefix costs one byte
        if len(compressed) < (len(json) - 1):
            json = compressed
            is_compressed = True
        base64d = base64_encode(json)
        if is_compressed:
            base64d = b"." + base64d
        return base64d


class URLSafeSerializer(URLSafeSerializerMixin, Serializer):
    """Signed, URL-safe serializer (JSON, zlib if shorter)."""


class URLSafeTimedSerializer(URLSafeSerializerMixin, TimedSerializer):
    """Timed variant of :class:`URLSafeSerializer`."""
