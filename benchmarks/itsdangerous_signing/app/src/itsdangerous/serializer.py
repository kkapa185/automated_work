"""Signed serialization."""
from __future__ import annotations

import hashlib
import json
import typing as t

from .encoding import want_bytes
from .exc import BadPayload, BadSignature
from .signer import Signer, _make_keys_list


def is_text_serializer(serializer: t.Any) -> bool:
    """True if the serializer's ``dumps`` returns str."""
    return isinstance(serializer.dumps({}), str)


class Serializer:
    """Serialize an object and sign the result."""

    default_serializer: t.Any = json
    default_signer: type = Signer
    default_fallback_signers: list = []
    default_signer_kwargs: dict = {
        "key_derivation": "hmac",
        "digest_method": hashlib.sha1,
    }

    def __init__(
        self,
        secret_key: str | bytes | t.Iterable[str | bytes],
        salt: str | bytes | None = b"itsdangerous",
        serializer: t.Any = None,
        signer: t.Any = None,
        signer_kwargs: dict[str, t.Any] | None = None,
        fallback_signers: list[t.Any] | None = None,
        serializer_kwargs: dict[str, t.Any] | None = None,
    ) -> None:
        self.secret_keys: list[bytes] = _make_keys_list(secret_key)
        if salt is not None:
            salt = want_bytes(salt)
        self.salt = salt
        if serializer is None:
            serializer = self.default_serializer
        self.serializer = serializer
        self.is_text_serializer = is_text_serializer(serializer)
        if signer is None:
            signer = self.default_signer
        self.signer = signer
        self.signer_kwargs = {**self.default_signer_kwargs, **(signer_kwargs or {})}
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
            is_text = is_text_serializer(serializer)
        try:
            if is_text:
                return serializer.loads(payload.decode("utf-8"))
            return serializer.loads(payload)
        except Exception as e:
            raise BadPayload(
                "Could not load the payload because an exception occurred"
                " on unserializing the data.",
                original_error=e,
            ) from e

    def dump_payload(self, obj: t.Any) -> bytes:
        return want_bytes(self.serializer.dumps(obj, **self.serializer_kwargs))

    def make_signer(self, salt: str | bytes | None = None) -> t.Any:
        if salt is None:
            salt = self.salt
        return self.signer(self.secret_keys, salt=salt, **self.signer_kwargs)

    def iter_unsigners(self, salt: str | bytes | None = None) -> t.Iterator[t.Any]:
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

    def dump(self, obj: t.Any, f: t.IO[t.Any], salt: str | bytes | None = None) -> None:
        f.write(self.dumps(obj, salt))

    def loads(self, s: str | bytes, salt: str | bytes | None = None, **kwargs: t.Any) -> t.Any:
        s = want_bytes(s)
        last_exception: BadSignature | None = None
        for signer in self.iter_unsigners(salt):
            try:
                return self.load_payload(signer.unsign(s))
            except BadSignature as err:
                last_exception = err
        raise t.cast(BadSignature, last_exception)

    def load(self, f: t.IO[t.Any], salt: str | bytes | None = None) -> t.Any:
        return self.loads(f.read(), salt)

    def loads_unsafe(self, s: str | bytes, salt: str | bytes | None = None) -> tuple[bool, t.Any]:
        return self._loads_unsafe_impl(s, salt)

    def _loads_unsafe_impl(
        self,
        s: str | bytes,
        salt: str | bytes | None,
        load_kwargs: dict[str, t.Any] | None = None,
        load_payload_kwargs: dict[str, t.Any] | None = None,
    ) -> tuple[bool, t.Any]:
        try:
            return True, self.loads(s, salt=salt, **(load_kwargs or {}))
        except BadPayload:
            return False, None
        except BadSignature as e:
            if e.payload is None:
                return False, None
            try:
                return False, self.load_payload(e.payload, **(load_payload_kwargs or {}))
            except BadPayload:
                return False, None

    def load_unsafe(self, f: t.IO[t.Any], salt: str | bytes | None = None) -> tuple[bool, t.Any]:
        return self.loads_unsafe(f.read(), salt=salt)
