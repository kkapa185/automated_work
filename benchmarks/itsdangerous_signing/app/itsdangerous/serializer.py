"""Serializers that sign their output."""
from __future__ import annotations

import json
import typing as t

from .encoding import want_bytes
from .exc import BadPayload, BadSignature
from .signer import Signer
from .timed import TimestampSigner


class _CompactJSON:
    """JSON with no whitespace."""

    @staticmethod
    def loads(payload: str | bytes) -> t.Any:
        return json.loads(payload)

    @staticmethod
    def dumps(obj: t.Any, **kwargs: t.Any) -> str:
        kwargs.setdefault("ensure_ascii", False)
        kwargs.setdefault("separators", (",", ":"))
        return json.dumps(obj, **kwargs)


_DEFAULT = object()


class Serializer:
    default_serializer: t.Any = _CompactJSON
    default_signer: type = Signer
    default_fallback_signers: list = []

    def __init__(
        self,
        secret_key: t.Any,
        salt: str | bytes | None = b"itsdangerous",
        serializer: t.Any = _DEFAULT,
        signer: t.Any = None,
        signer_kwargs: dict | None = None,
        fallback_signers: list | None = None,
        serializer_kwargs: dict | None = None,
    ):
        if isinstance(secret_key, (str, bytes)):
            self.secret_keys: list[bytes] = [want_bytes(secret_key)]
        else:
            self.secret_keys = [want_bytes(k) for k in secret_key]
        self.salt = want_bytes(salt) if salt is not None else None
        if serializer is _DEFAULT or serializer is None:
            serializer = self.default_serializer
        self.serializer = serializer
        self.is_text_serializer = isinstance(serializer.dumps({}), str)
        if signer is None:
            signer = self.default_signer
        self.signer = signer
        self.signer_kwargs = signer_kwargs or {}
        if fallback_signers is None:
            fallback_signers = list(self.default_fallback_signers)
        self.fallback_signers = fallback_signers
        self.serializer_kwargs = serializer_kwargs or {}

    @property
    def secret_key(self) -> bytes:
        return self.secret_keys[-1]

    def load_payload(self, payload: bytes, serializer: t.Any = None) -> t.Any:
        if serializer is None:
            serializer = self.serializer
            is_text = self.is_text_serializer
        else:
            is_text = isinstance(serializer.dumps({}), str)
        try:
            if is_text:
                return serializer.loads(payload.decode("utf-8"))
            return serializer.loads(payload)
        except Exception as e:
            raise BadPayload(
                "Could not load the payload because an exception"
                " occurred on unserializing the data.",
                original_error=e,
            ) from e

    def dump_payload(self, obj: t.Any) -> bytes:
        return want_bytes(self.serializer.dumps(obj, **self.serializer_kwargs))

    def make_signer(self, salt: str | bytes | None = None) -> Signer:
        if salt is None:
            salt = self.salt
        return self.signer(self.secret_keys, salt=salt, **self.signer_kwargs)

    def iter_unsigners(self, salt: str | bytes | None = None) -> t.Iterator[Signer]:
        if salt is None:
            salt = self.salt
        yield self.make_signer(salt)
        for fallback in self.fallback_signers:
            if isinstance(fallback, dict):
                kwargs = fallback
                fallback = self.signer
            elif isinstance(fallback, tuple):
                fallback, kwargs = fallback
            else:
                kwargs = self.signer_kwargs
            yield fallback(self.secret_keys, salt=salt, **kwargs)

    def dumps(self, obj: t.Any, salt: str | bytes | None = None) -> t.Any:
        payload = want_bytes(self.dump_payload(obj))
        rv = self.make_signer(salt).sign(payload)
        if self.is_text_serializer:
            return rv.decode("utf-8")
        return rv

    def dump(self, obj: t.Any, f: t.IO, salt: str | bytes | None = None) -> None:
        f.write(self.dumps(obj, salt))

    def loads(self, s: str | bytes, salt: str | bytes | None = None, **kwargs: t.Any) -> t.Any:
        s = want_bytes(s)
        last_exception: BadSignature | None = None
        for signer in self.iter_unsigners(salt):
            try:
                return self.load_payload(signer.unsign(s, **kwargs))
            except BadSignature as err:
                last_exception = err
        assert last_exception is not None
        raise last_exception

    def load(self, f: t.IO, salt: str | bytes | None = None) -> t.Any:
        return self.loads(f.read(), salt)

    def _loads_unsafe_impl(self, s, salt, load_kwargs=None, load_payload_kwargs=None):
        try:
            return True, self.loads(s, salt=salt, **(load_kwargs or {}))
        except BadSignature as e:
            if e.payload is None:
                return False, None
            try:
                return False, self.load_payload(e.payload, **(load_payload_kwargs or {}))
            except BadPayload:
                return False, None

    def loads_unsafe(self, s: str | bytes, salt: str | bytes | None = None) -> tuple[bool, t.Any]:
        return self._loads_unsafe_impl(s, salt)

    def load_unsafe(self, f: t.IO, salt: str | bytes | None = None) -> tuple[bool, t.Any]:
        return self.loads_unsafe(f.read(), salt=salt)


class TimedSerializer(Serializer):
    """Serializer using :class:`TimestampSigner`."""

    default_signer = TimestampSigner

    def loads(  # type: ignore[override]
        self,
        s: str | bytes,
        max_age: int | None = None,
        return_timestamp: bool = False,
        salt: str | bytes | None = None,
    ) -> t.Any:
        s = want_bytes(s)
        last_exception: BadSignature | None = None
        for signer in self.iter_unsigners(salt):
            try:
                base64d, timestamp = signer.unsign(s, max_age=max_age, return_timestamp=True)
                payload = self.load_payload(base64d)
                if return_timestamp:
                    return payload, timestamp
                return payload
            except BadSignature as err:
                last_exception = err
        assert last_exception is not None
        raise last_exception

    def loads_unsafe(self, s, salt=None, max_age=None):  # type: ignore[override]
        return self._loads_unsafe_impl(s, salt, load_kwargs={"max_age": max_age})
