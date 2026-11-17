"""URL-safe serializers: compact JSON, optional zlib, base64."""
import json
import zlib

from .encoding import base64_decode
from .encoding import base64_encode
from .exc import BadPayload
from .serializer import Serializer
from .timed import TimedSerializer


class _CompactJSON:
    """JSON with no whitespace after separators."""

    @staticmethod
    def loads(payload):
        return json.loads(payload)

    @staticmethod
    def dumps(obj):
        return json.dumps(obj, separators=(",", ":"))


class URLSafeSerializerMixin:
    """Payload is compact JSON, zlib-compressed (``.`` prefix) when shorter,
    then URL-safe base64 without padding."""

    default_serializer = _CompactJSON

    def load_payload(self, payload, *args, **kwargs):
        decompress = False
        if payload.startswith(b"."):
            payload = payload[1:]
            decompress = True
        try:
            data = base64_decode(payload)
        except Exception as e:
            raise BadPayload(
                "Could not base64 decode the payload because of an exception",
                original_error=e,
            ) from e
        if decompress:
            try:
                data = zlib.decompress(data)
            except Exception as e:
                raise BadPayload(
                    "Could not zlib decompress the payload before decoding"
                    " the payload",
                    original_error=e,
                ) from e
        return super().load_payload(data, *args, **kwargs)

    def dump_payload(self, obj):
        data = super().dump_payload(obj)
        compressed = zlib.compress(data)
        is_compressed = len(compressed) < len(data)
        if is_compressed:
            data = compressed
        out = base64_encode(data)
        if is_compressed:
            out = b"." + out
        return out


class URLSafeSerializer(URLSafeSerializerMixin, Serializer):
    """Serializer whose tokens are safe in URLs."""


class URLSafeTimedSerializer(URLSafeSerializerMixin, TimedSerializer):
    """URL-safe serializer with timestamps."""
