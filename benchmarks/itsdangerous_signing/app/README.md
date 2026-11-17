# itsdangerous

Stdlib-only (Python >= 3.9) library that signs data so it can travel through untrusted channels
(cookies, URLs, e-mail) and be verified on return. Wire-compatible with the 2.x token format.

## Install / test
```
pip install -e .
pip install pytest && python -m pytest
```

## Usage
```python
from itsdangerous import Signer, TimestampSigner, URLSafeTimedSerializer, BadSignature, SignatureExpired

Signer("secret").sign("hi")                  # b'hi.<sig>'
s = URLSafeTimedSerializer(["old", "new"])   # key rotation: newest last
token = s.dumps({"user": 1})
try:
    s.loads(token, max_age=3600)
except SignatureExpired: ...
except BadSignature: ...
```

## Format
* Signature = unpadded URL-safe base64 of HMAC(derived key, value); token = `value + sep + signature`.
* Key derivation: `concat` = H(salt+key); `django-concat` (Signer default) = H(salt+"signer"+key);
  `hmac` = HMAC(key, salt) (Serializer default, with SHA-1); `none` = key.
* `TimestampSigner`: `value.b64(big-endian timestamp).signature`; the signature covers value+sep+timestamp.
* `Serializer` uses `json` (default formatting). URL-safe serializers use compact JSON, zlib-compress it
  when that makes the token shorter (prefix `.`), then unpadded base64.
* Signatures are compared with `hmac.compare_digest`.

Errors: `BadData` > `BadSignature` > `BadTimeSignature` > `SignatureExpired`; `BadSignature` > `BadHeader`;
`BadData` > `BadPayload`.
