# itsdangerous

Pure-standard-library (Python >= 3.9) implementation of signed tokens for untrusted channels
(cookies, URLs, e-mail), wire-compatible with the itsdangerous 2.x format.

## Install / test
```
pip install -e .          # no runtime dependencies
pip install pytest
python -m pytest
python examples/demo.py   # smoke run
```

## Usage
```python
from itsdangerous import Signer, TimestampSigner, URLSafeTimedSerializer

Signer("secret").sign(b"hello")          # b'hello.<sig>'
TimestampSigner("secret").unsign(token, max_age=60)

s = URLSafeTimedSerializer(["old-key", "new-key"], salt="activate")  # rotation: newest last
token = s.dumps({"user": 42})
s.loads(token, max_age=3600)
```

## Format
* Signature = urlsafe-base64 (no padding) of HMAC(derived key, value); token = `value + sep + signature`.
* Key derivation: `concat` = H(salt+key); `django-concat` (default) = H(salt+"signer"+key);
  `hmac` = HMAC(key, salt); `none` = key. Default digest is SHA-1.
* `TimestampSigner`: `value.<b64 big-endian int timestamp>.<sig>`; timestamps are UTC-aware datetimes.
* `Serializer` payload is compact JSON, signed with salt `itsdangerous`. URL-safe serializers
  zlib-compress when shorter (prefix `.`) and base64 encode.
* Signature comparison uses `hmac.compare_digest`. Multiple keys are tried newest first; `fallback_signers`
  allow migrating signer settings.
* Errors: `BadData` > `BadSignature` > `BadTimeSignature` > `SignatureExpired`; `BadSignature` > `BadHeader`;
  `BadData` > `BadPayload`. `BadHeader` exists for API compatibility only (no JWS headers are produced).
