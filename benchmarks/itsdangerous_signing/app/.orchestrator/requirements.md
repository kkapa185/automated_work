# Requirements: itsdangerous (clean-room Python library)

## Product
A stdlib-only Python (>=3.9) package `itsdangerous` that signs data for untrusted channels and verifies it on return, wire-compatible with the itsdangerous 2.x token format and exposing the same public API (Signer, TimestampSigner, Serializer, TimedSerializer, URLSafeSerializer, URLSafeTimedSerializer, exception hierarchy, helpers). Classification: library; src layout, pytest suite, README, pyproject.toml.

## Acceptance criteria
R1. `want_bytes(s, encoding="utf-8", errors="strict")` returns bytes for str, passes bytes through.
R2. `base64_encode(str|bytes)` -> URL-safe base64 bytes, no padding; `base64_decode` accepts str/bytes, restores padding, raises `BadData("Invalid base64-encoded data")` on invalid input. Also `int_to_bytes` / `bytes_to_int` (big-endian minimal) helpers.
R3. `Signer.__init__(secret_key, salt=b"itsdangerous.Signer", sep=".", key_derivation="django-concat", digest_method=hashlib.sha1, algorithm=None)`; key list accepted (newest last); str/bytes keys; salt/sep None-handling: salt None -> default salt. Sep in URL-safe base64 alphabet (A-Za-z0-9-_=) -> ValueError.
R4. Key derivation: concat = digest(salt+key); django-concat = digest(salt+b"signer"+key); hmac = HMAC(key, msg=salt, digest); none = key; unknown -> TypeError. `derive_key(secret_key=None)` uses newest key by default.
R5. Algorithm default `HMACAlgorithm(digest_method)`; `NoneAlgorithm` (empty signature) and `HMACAlgorithm` exist; `SigningAlgorithm.verify_signature` uses constant-time compare (hmac.compare_digest).
R6. `get_signature(value)` -> bytes b64 no padding; `sign(value)` = value+sep+sig bytes; `verify_signature(value, sig)` tries all keys (newest first), returns bool, False on bad base64; `unsign` raises `BadSignature("No \"%s\" found in value")` when no sep, `BadSignature("Signature b'..' does not match", payload=value)` on mismatch; returns value bytes; `validate` returns bool.
R7. `TimestampSigner`: token `value.b64(ts).sig`; sig covers value+sep+ts; `get_timestamp()` int(time.time()); `timestamp_to_datetime` -> aware UTC; `unsign(signed, max_age=None, return_timestamp=False)` errors: `BadTimeSignature("timestamp missing", payload=value)`, `BadTimeSignature("Malformed timestamp", payload, date_signed?)`, `SignatureExpired("Signature age %s > %s seconds")` with date_signed, and age<0 -> `SignatureExpired("Signature age %s < 0 seconds")`; max_age check is `age > max_age`. A bad signature raises BadSignature (BadTimeSignature if timestamp part present is not required). `validate(signed, max_age=None)`.
R8. Exceptions: BadData(message; `.message`; str() = message); BadSignature(message, payload=None); BadTimeSignature(message, payload, date_signed); SignatureExpired subclass; BadHeader(message, payload, header, original_error) subclass of BadSignature; BadPayload(message, original_error) subclass of BadData.
R9. `Serializer(secret_key, salt=b"itsdangerous", serializer=json, signer=Signer, signer_kwargs=None, fallback_signers=None, serializer_kwargs=None)`; `dumps` -> signed str (or bytes if serializer is binary); `loads` raises BadSignature on tamper, BadPayload on undecodable payload; `dump/load` for file-like; `loads_unsafe/load_unsafe` return `(ok, payload)` with payload still decoded on bad signature. Default serializer: `json.dumps(obj)` default separators. `make_signer(salt)`, `iter_unsigners`, fallback_signers entries may be class, dict, or (cls, kwargs) tuple. Salt None → default salt; signer_kwargs default key_derivation "hmac"? NO: default signer kwargs `{"key_derivation":"hmac","digest_method":sha1}` (2.x default) — assumed per 2.x Serializer.default_signer_kwargs.
R10. `TimedSerializer.loads(s, max_age=None, return_timestamp=False, salt=None)`; uses TimestampSigner; `loads_unsafe` supports max_age.
R11. `URLSafeSerializer`/`URLSafeTimedSerializer`: dumps payload = compact JSON, zlib-compress when strictly shorter (prefix `.`), b64 no padding; loads reverses; bad base64 / zlib -> BadPayload.
R12. Rotation: list of keys works for Signer and Serializer; sign newest, accept any.
R13. Constant-time comparison (`hmac.compare_digest`) used for signatures.
R14. Known-answer vectors computed independently in tests via hashlib/hmac/base64 from format definition.
R15. Packaging: pyproject.toml, `pip install -e .` and `pytest` work; stdlib only; `__version__` 2.x string; `py.typed` optional.

## Assumptions
- Unspecified details follow the 2.x conventions (default_signer_kwargs hmac/sha1 for Serializer; Signer itself defaults django-concat).
- Serializer `dumps` returns str when the serializer yields text, bytes when binary (is_text_serializer test: dumps({}) is str).
- Hashes accept `hashlib.sha1` callable; `algorithm` overrides.

## Test strategy
- tests/test_signer.py (R3-R6, R12, R13, R14), test_timed.py (R7), test_serializer.py (R9, R10, R12), test_url_safe.py (R11), test_encoding.py (R1, R2, R8), all unit/pytest with monkeypatched time and independently computed vectors.
