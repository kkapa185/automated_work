"""Serialize arbitrary objects and sign the result."""
import json

from .encoding import want_bytes
from .exc import BadPayload
from .exc import BadSignature
from .signer import Signer


def _make_keys_list(secret_key):
    if isinstance(secret_key, (str, bytes)):
        return [want_bytes(secret_key)]
    return [want_bytes(k) for k in secret_key]


class Serializer:
    """Wraps a signer so any object the ``serializer`` handles can be signed."""

    default_serializer = json
    default_signer = Signer
    default_fallback_signers = []

    def __init__(
        self,
        secret_key,
        salt=b"itsdangerous",
        serializer=None,
        signer=None,
        signer_kwargs=None,
        fallback_signers=None,
    ):
        self.secret_keys = _make_keys_list(secret_key)
        if salt is not None:
            salt = want_bytes(salt)
        self.salt = salt
        if serializer is None:
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

    @property
    def secret_key(self):
        return self.secret_keys[-1]

    def load_payload(self, payload, serializer=None):
        """Unserialize verified (or deliberately unsafe) payload bytes."""
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

    def dump_payload(self, obj):
        """Serialize ``obj`` to bytes (before signing)."""
        return want_bytes(self.serializer.dumps(obj))

    def make_signer(self, salt=None):
        if salt is None:
            salt = self.salt
        return self.signer(self.secret_keys, salt=salt, **self.signer_kwargs)

    def iter_unsigners(self, salt=None):
        """Signers to try when loading: primary first, then fallbacks."""
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

    def dumps(self, obj, salt=None):
        """Serialize and sign; ``str`` for text serializers, else ``bytes``."""
        payload = self.dump_payload(obj)
        rv = self.make_signer(salt).sign(payload)
        if self.is_text_serializer:
            return rv.decode("utf-8")
        return rv

    def dump(self, obj, f, salt=None):
        f.write(self.dumps(obj, salt))

    def loads(self, s, salt=None):
        s = want_bytes(s)
        last_exception = None
        for signer in self.iter_unsigners(salt):
            try:
                return self.load_payload(signer.unsign(s))
            except BadSignature as err:
                last_exception = err
        raise last_exception

    def load(self, f, salt=None):
        return self.loads(f.read(), salt)

    def _loads_unsafe_impl(self, s, salt, **kwargs):
        try:
            return True, self.loads(s, salt=salt, **kwargs)
        except BadSignature as e:
            if e.payload is None:
                return False, None
            try:
                return False, self.load_payload(e.payload)
            except BadPayload:
                return False, None

    def loads_unsafe(self, s, salt=None):
        """``(signature_ok, obj_or_None)``; never trust ``obj`` if not ok."""
        return self._loads_unsafe_impl(s, salt)

    def load_unsafe(self, f, salt=None):
        return self.loads_unsafe(f.read(), salt)
