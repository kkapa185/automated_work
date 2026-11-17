"""Securely sign data for untrusted channels."""
from .encoding import base64_decode, base64_encode, want_bytes
from .exc import (
    BadData,
    BadHeader,
    BadPayload,
    BadSignature,
    BadTimeSignature,
    SignatureExpired,
)
from .serializer import Serializer
from .signer import HMACAlgorithm, NoneAlgorithm, Signer, SigningAlgorithm
from .timed import TimedSerializer, TimestampSigner
from .url_safe import URLSafeSerializer, URLSafeTimedSerializer

__version__ = "2.2.0"

__all__ = [
    "BadData", "BadHeader", "BadPayload", "BadSignature", "BadTimeSignature",
    "SignatureExpired", "Serializer", "Signer", "SigningAlgorithm",
    "HMACAlgorithm", "NoneAlgorithm", "TimedSerializer", "TimestampSigner",
    "URLSafeSerializer", "URLSafeTimedSerializer", "base64_decode",
    "base64_encode", "want_bytes",
]
