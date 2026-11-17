"""Independent reference implementation of the wire format (hashlib/hmac/base64
only) used to compute known-answer vectors. Does not import the package."""
import base64
import hashlib
import hmac


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def derive(key, salt, mode="django-concat", digest=hashlib.sha1):
    if mode == "concat":
        return digest(salt + key).digest()
    if mode == "django-concat":
        return digest(salt + b"signer" + key).digest()
    if mode == "hmac":
        return hmac.new(key, salt, digest).digest()
    if mode == "none":
        return key
    raise ValueError(mode)


def signature(value, key, salt, mode="django-concat", digest=hashlib.sha1):
    k = derive(key, salt, mode, digest)
    return b64(hmac.new(k, value, digest).digest())


def sign(value, key, salt=b"itsdangerous.Signer", sep=b".", **kw):
    return value + sep + signature(value, key, salt, **kw)


def ts_bytes(ts):
    return ts.to_bytes((ts.bit_length() + 7) // 8, "big")


def sign_ts(value, ts, key, salt=b"itsdangerous.Signer", sep=b".", **kw):
    body = value + sep + b64(ts_bytes(ts))
    return body + sep + signature(body, key, salt, **kw)
