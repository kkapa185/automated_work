"""Signing of bytes values."""
import hashlib
import hmac

from .encoding import base64_decode
from .encoding import base64_encode
from .encoding import want_bytes
from .exc import BadData
from .exc import BadSignature

_BASE64_ALPHABET = (
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
)


class SigningAlgorithm:
    """Subclasses must implement :meth:`get_signature`."""

    def get_signature(self, key, value):
        raise NotImplementedError()

    def verify_signature(self, key, value, sig):
        """Constant-time comparison of ``sig`` with the computed signature."""
        return hmac.compare_digest(sig, self.get_signature(key, value))


class NoneAlgorithm(SigningAlgorithm):
    """Provides an algorithm that does not perform any signing and
    returns an empty signature."""

    def get_signature(self, key, value):
        return b""


class HMACAlgorithm(SigningAlgorithm):
    """HMAC signing using the given digest method (default SHA-1)."""

    default_digest_method = staticmethod(hashlib.sha1)

    def __init__(self, digest_method=None):
        if digest_method is None:
            digest_method = self.default_digest_method
        self.digest_method = digest_method

    def get_signature(self, key, value):
        mac = hmac.new(key, msg=value, digestmod=self.digest_method)
        return mac.digest()


class Signer:
    """Signs bytes by appending ``sep`` and a URL-safe base64 HMAC signature."""

    default_digest_method = staticmethod(hashlib.sha1)
    default_key_derivation = "django-concat"

    def __init__(
        self,
        secret_key,
        salt=b"itsdangerous.Signer",
        sep=b".",
        key_derivation=None,
        digest_method=None,
        algorithm=None,
    ):
        if isinstance(secret_key, (str, bytes)):
            self.secret_keys = [want_bytes(secret_key)]
        else:
            self.secret_keys = [want_bytes(k) for k in secret_key]
        self.sep = want_bytes(sep)
        if set(self.sep) & set(_BASE64_ALPHABET):
            raise ValueError(
                "The given separator cannot be used because it may be"
                " contained in the signature itself. ASCII letters, digits,"
                " and '-_=' must not be used."
            )
        self.salt = want_bytes(salt)
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
    def secret_key(self):
        """The newest secret key."""
        return self.secret_keys[-1]

    def derive_key(self, secret_key=None):
        """Derive the signing key from a secret key (default: the newest)."""
        if secret_key is None:
            secret_key = self.secret_keys[-1]
        else:
            secret_key = want_bytes(secret_key)

        if self.key_derivation == "concat":
            return self.digest_method(self.salt + secret_key).digest()
        if self.key_derivation == "django-concat":
            return self.digest_method(self.salt + b"signer" + secret_key).digest()
        if self.key_derivation == "hmac":
            mac = hmac.new(secret_key, digestmod=self.digest_method)
            mac.update(self.salt)
            return mac.digest()
        if self.key_derivation == "none":
            return secret_key
        raise TypeError("Unknown key derivation method")

    def get_signature(self, value):
        """Signature (base64, bytes) of ``value`` with the newest key."""
        value = want_bytes(value)
        key = self.derive_key()
        sig = self.algorithm.get_signature(key, value)
        return base64_encode(sig)

    def sign(self, value):
        """``value`` + separator + signature, as bytes."""
        value = want_bytes(value)
        return value + self.sep + self.get_signature(value)

    def verify_signature(self, value, sig):
        """Check ``sig`` against ``value`` using every key, newest first."""
        try:
            sig = base64_decode(sig)
        except BadData:
            return False
        value = want_bytes(value)
        for secret_key in reversed(self.secret_keys):
            key = self.derive_key(secret_key)
            if self.algorithm.verify_signature(key, value, sig):
                return True
        return False

    def unsign(self, signed_value):
        """Return the value if the signature is valid, else raise
        :exc:`~itsdangerous.exc.BadSignature`."""
        signed_value = want_bytes(signed_value)
        if self.sep not in signed_value:
            raise BadSignature(
                f'No "{self.sep.decode("utf-8", "replace")}" found in value'
            )
        value, sig = signed_value.rsplit(self.sep, 1)
        if self.verify_signature(value, sig):
            return value
        raise BadSignature(f"Signature {sig!r} does not match", payload=value)

    def validate(self, signed_value):
        """True if ``signed_value`` has a valid signature."""
        try:
            self.unsign(signed_value)
            return True
        except BadSignature:
            return False
