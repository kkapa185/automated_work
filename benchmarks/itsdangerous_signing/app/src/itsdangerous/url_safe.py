"""URL-safe serializers."""
from __future__ import annotations

import json
import typing as t
import zlib

from .encoding import base64_decode, base64_encode
from .exc import BadPayload
from .serializer import Serializer
from .timed import TimedSerializer


class _CompactJSON:
    @staticmethod
    def loads(payload: str) -> t.Any:
        return json.loads(payload)

    @staticmethod
    def dumps(obj: t.Any, **kwargs: t.Any) -> str:
        kwargs.setdefault("separators", (",", ":"))
        return json.dumps(obj, **kwargs)


class URLSafeSerializerMixin:
    """Compress (when smaller) and base64-encode the payload."""

    default_serializer = _CompactJSON

    def load_payload(self, payload: bytes, *args: t.Any, **kwargs: t.Any) -> t.Any:
        decompress = False
        if payload.startswith(b"."):
            payload = payload[1:]
            decompress = True
        try:
            json_data = base64_decode(payload)
        except Exception as e:
            raise BadPayload(
                "Could not base64 decode the payload because of an exception",
                original_error=e,
            ) from e
        if decompress:
            try:
                json_data = zlib.decompress(json_data)
            except Exception as e:
                raise BadPayload(
                    "Could not zlib decompress the payload before decoding the payload",
                    original_error=e,
                ) from e
        return super().load_payload(json_data, *args, **kwargs)  # type: ignore

    def dump_payload(self, obj: t.Any) -> bytes:
        json_data = super().dump_payload(obj)  # type: ignore
        is_compressed = False
        compressed = zlib.compress(json_data)
        # The "." prefix costs one byte, so only compress if still shorter.
        if len(compressed) < (len(json_data) - 1):
            json_data = compressed
            is_compressed = True
        encoded = base64_encode(json_data)
        if is_compressed:
            encoded = b"." + encoded
        return encoded


class URLSafeSerializer(URLSafeSerializerMixin, Serializer):
    """Signed, URL-safe serializer."""


class URLSafeTimedSerializer(URLSafeSerializerMixin, TimedSerializer):
    """Timestamped, signed, URL-safe serializer."""
