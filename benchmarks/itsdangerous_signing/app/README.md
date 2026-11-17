# itsdangerous

Sign data so it can travel through untrusted channels (cookies, URLs, e-mail)
and be verified on the way back. Pure Python (>= 3.9), standard library only,
and wire-compatible with the widely deployed `itsdangerous` 2.x token format.

## Install / test / run

```
python3 -m pip install -e .[test]   # or: pip install pytest
python3 -m pytest                   # full suite
python3 examples/demo.py            # smoke demo
```

## Usage

```python
from itsdangerous import Signer, TimestampSigner, URLSafeTimedSerializer

Signer("secret-key").sign("my string")
# b'my string.wh6tMHxLgJqB6oY1uT73iMlyrOA'

s = URLSafeTimedSerializer("secret-key", salt="activate")
token = s.dumps({"id": 42})
s.loads(token, max_age=3600)      # raises SignatureExpired / BadSignature
```

Key rotation: pass a list of keys, oldest to newest; the newest signs, all are
accepted. `fallback_signers` lets you migrate signing parameters.

## Format

* Signing key: `concat` = digest(salt+key); `django-concat` (default) =
  digest(salt+b"signer"+key); `hmac` = HMAC(key, salt); `none` = key.
* Signature = urlsafe-base64 (no padding) of HMAC(derived key, value).
  Token = `value + sep + signature`. `sep` must not be a base64 URL-safe char.
* `TimestampSigner`: `value . b64(big-endian timestamp) . signature`; the
  signature covers `value.timestamp`.
* `Serializer`: default `json.dumps(obj)` formatting, salt `b"itsdangerous"`,
  returns `str` for text serializers. URL-safe variants use compact JSON,
  zlib-compressed (prefixed `.`) only if strictly shorter, then base64.
* Signature comparison is constant-time (`hmac.compare_digest`).

## Layout

`itsdangerous/{encoding,exc,signer,timed,serializer,url_safe}.py`; tests in
`tests/` (known-answer vectors come from the independent reference in
`tests/kat.py`, which only uses `hashlib`/`hmac`/`base64`). Requirements and
assumptions: `.orchestrator/requirements.md`.
