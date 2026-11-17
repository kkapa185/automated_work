"""Plain signing."""
from __future__ import annotations

import hashlib
import hmac
import typing as t

from .encoding import base64_decode, base64_encode, want_bytes
from .exc import BadSignature

_base64_alphabet = (
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
)


class SigningAlgorithm:
    """Base for signature algorithms."""

    def get_signature(self, key: bytes, value: bytes) -> bytes:
        raise NotImplementedError()

    def verify_signature(self, key: bytes, value: bytes, sig: bytes) -> bool:
        return hmac.compare_digest(sig, self.get_signature(key, value))


class NoneAlgorithm(SigningAlgorithm):
    """Produces an empty signature."""

    def get_signature(self, key: bytes, value: bytes) -> bytes:
        return b""


class HMACAlgorithm(SigningAlgorithm):
    """HMAC with a configurable digest."""

    default_digest_method: t.Any = staticmethod(hashlib.sha1)

    def __init__(self, digest_method: t.Any = None) -> None:
        if digest_method is None:
            digest_method = self.default_digest_method
        self.digest_method = digest_method

    def get_signature(self, key: bytes, value: bytes) -> bytes:
        return hmac.new(key, msg=value, digestmod=self.digest_method).digest()


def _make_keys_list(secret_key: str | bytes | t.Iterable[str | bytes]) -> list[bytes]:
    if isinstance(secret_key, (str, bytes)):
        return [want_bytes(secret_key)]
    return [want_bytes(k) for k in secret_key]


class Signer:
    """Sign and unsign bytes as ``value + sep + signature``."""

    default_digest_method: t.Any = staticmethod(hashlib.sha1)
    default_key_derivation: str = "django-concat"

    def __init__(
        self,
        secret_key: str | bytes | t.Iterable[str | bytes],
        salt: str | bytes | None = b"itsdangerous.Signer",
        sep: str | bytes = b".",
        key_derivation: str | None = None,
        digest_method: t.Any = None,
        algorithm: SigningAlgorithm | None = None,
    ) -> None:
        #: Keys oldest to newest; the last signs, all verify.
        self.secret_keys: list[bytes] = _make_keys_list(secret_key)
        if salt is None:
            salt = b"itsdangerous.Signer"
        self.sep: bytes = want_bytes(sep)
        if self.sep in _base64_alphabet or any(c in _base64_alphabet for c in self.sep):
            raise ValueError(
                "The given separator cannot be used because it may be"
                " contained in the signature itself. ASCII letters, digits,"
                " and '-_=' must not be used."
            )
        if not self.sep:
            raise ValueError("The separator must not be empty.")
        self.salt: bytes = want_bytes(salt)
        if key_derivation is None:
            key_derivation = self.default_key_derivation
        self.key_derivation = key_derivation
        if digest_method is None:
            digest_method = self.default_digest_method
        self.digest_method = digest_method
        if algorithm is None:
            algorithm = HMACAlgorithm(self.digest_method)
        self.algorithm = algorithm

    @property
    def secret_key(self) -> bytes:
        """The newest secret key."""
        return self.secret_keys[-1]

    def derive_key(self, secret_key: str | bytes | None = None) -> bytes:
        """Derive the HMAC key from ``secret_key`` (default: the newest)."""
        if secret_key is None:
            secret_key = self.secret_keys[-1]
        else:
            secret_key = want_bytes(secret_key)

        if self.key_derivation == "concat":
            return self.digest_method(self.salt + secret_key).digest()  # type: ignore
        if self.key_derivation == "django-concat":
            return self.digest_method(  # type: ignore
                self.salt + b"signer" + secret_key
            ).digest()
        if self.key_derivation == "hmac":
            mac = hmac.new(secret_key, digestmod=self.digest_method)
            mac.update(self.salt)
            return mac.digest()
        if self.key_derivation == "none":
            return secret_key
        raise TypeError("Unknown key derivation method")

    def get_signature(self, value: str | bytes) -> bytes:
        """Unpadded URL-safe base64 signature of ``value``."""
        value = want_bytes(value)
        key = self.derive_key()
        sig = self.algorithm.get_signature(key, value)
        return base64_encode(sig)

    def sign(self, value: str | bytes) -> bytes:
        value = want_bytes(value)
        return value + self.sep + self.get_signature(value)

    def verify_signature(self, value: str | bytes, sig: str | bytes) -> bool:
        """Check ``sig`` against every known key, newest first."""
        try:
            sig = base64_decode(sig)
        except Exception:
            return False
        value = want_bytes(value)
        for secret_key in reversed(self.secret_keys):
            key = self.derive_key(secret_key)
            if self.algorithm.verify_signature(key, value, sig):
                return True
        return False

    def unsign(self, signed_value: str | bytes) -> bytes:
        signed_value = want_bytes(signed_value)
        if self.sep not in signed_value:
            raise BadSignature(f'No "{self.sep.decode("utf-8", "replace")}" found in value')
        value, sig = signed_value.rsplit(self.sep, 1)
        if self.verify_signature(value, sig):
            return value
        raise BadSignature(f"Signature {sig!r} does not match", payload=value)

    def validate(self, signed_value: str | bytes) -> bool:
        try:
            self.unsign(signed_value)
            return True
        except BadSignature:
            return False
