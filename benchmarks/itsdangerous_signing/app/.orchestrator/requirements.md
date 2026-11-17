# Requirements — itsdangerous (clean-room, spec-derived)

## Product
A pure-stdlib Python (>=3.9) library `itsdangerous` that signs data for untrusted channels and verifies it on return,
wire-compatible with the itsdangerous 2.x token format and exposing the same public API (Signer, TimestampSigner,
Serializer, TimedSerializer, URLSafeSerializer, URLSafeTimedSerializer, exceptions, helpers).

## Acceptance criteria
R1. `want_bytes(s, encoding="utf-8", errors="strict")` returns bytes for str (encoded) or bytes (unchanged).
R2. `base64_encode(str|bytes)` -> URL-safe base64 bytes, no padding. `base64_decode(str|bytes)` re-pads, decodes; invalid input raises `BadData("Invalid base64-encoded data")`.
R3. `Signer.__init__(secret_key, salt=b"itsdangerous.Signer", sep=".", key_derivation="django-concat", digest_method=hashlib.sha1, algorithm=None)`; salt/sep/keys coerced to bytes; `secret_key` may be str/bytes or iterable of keys (newest last); `salt=None` -> default salt; `sep` in URL-safe base64 alphabet raises `ValueError`.
R4. Key derivation: concat=digest(salt+key); django-concat=digest(salt+b"signer"+key); hmac=HMAC(key,msg=salt,digest); none=key; unknown mode raises TypeError. Default digest sha1. `derive_key(secret_key=None)` uses newest key by default.
R5. Signature = b64url-nopad(HMAC(derived key, value)); algorithm default HMAC with digest_method. `get_signature`, `sign` = value+sep+sig (bytes), `verify_signature(value, sig)` tries all keys (newest first) with constant-time compare (`hmac.compare_digest`); undecodable sig -> False.
R6. `unsign`: no sep -> `BadSignature('No "." found in value')`; bad signature -> `BadSignature("Signature %r does not match", payload=value)`; returns value bytes. `validate` returns bool. `signed` may be str.
R7. `TimestampSigner`: token `value.ts.sig`, ts = b64url-nopad of big-endian minimal-length int; signature covers `value.ts`; `get_timestamp()` = int(time.time()); `timestamp_to_datetime` -> aware UTC datetime. `unsign(signed, max_age=None, return_timestamp=False)`; errors: bad sig, `timestamp missing` (BadTimeSignature, payload) when no sep in the unsigned part, malformed timestamp -> `BadTimeSignature("Malformed timestamp")`, `Signature age %d > %d seconds` (SignatureExpired, date_signed); age<0 -> `Signature age %d < 0 seconds`; max_age boundary: expired only if age > max_age. `validate(signed, max_age=None)`.
R8. Exceptions hierarchy: BadData(message) -> BadSignature(message, payload) -> BadTimeSignature(message, payload, date_signed) -> SignatureExpired; BadSignature -> BadHeader(message, payload, header, original_error); BadData -> BadPayload(message, original_error). `.message`, `.payload`, `.date_signed`, `str()` = message.
R9. `Serializer(secret_key, salt=b"itsdangerous", serializer=json, signer=Signer, signer_kwargs=None, fallback_signers=None)`: `dumps(obj, salt=None)` -> signed (str for text serializers, bytes for binary); `loads(s, salt=None, **kw)`; `dump/load` file variants; `loads_unsafe/load_unsafe` -> `(ok, payload)`; default JSON compact (separators `,` `:`); signer built with Signer defaults (django-concat, sha1) unless signer_kwargs given; fallback signers (class, kwargs dict, or (class, kwargs) tuple) tried on failure; payload decode failure -> `BadPayload`; `is_text_serializer`.
R10. `TimedSerializer.loads(s, max_age=None, return_timestamp=False, salt=None)`, `loads_unsafe`; default signer TimestampSigner.
R11. `URLSafeSerializer`/`URLSafeTimedSerializer`: dump payload = compact JSON, zlib-compressed if shorter (then `.` prefix), b64url-nopad; load reverses; bad base64/zlib/json -> BadPayload.
R12. Default Serializer wire format: `json_compact . sig` with Signer(salt=b"itsdangerous") with default django-concat key derivation. Known-answer vectors computed independently with hmac/hashlib in tests.
R13. Package pure stdlib, pyproject.toml, `python -m pytest` passes, README.

## Assumptions
- Header-less (no JWS) — BadHeader exists only for API compatibility.
- Serializer secret_key list rotation supported via Signer; `salt` in dumps overrides instance salt.
- `Serializer.make_signer(salt)`; `iter_unsigners(salt)`.

## Test strategy
tests/ with pytest: known-answer vectors (R5,R12) using independent hmac computation; each key derivation (R4); tampering/expiry/rotation (R6,R7,R3); exceptions (R8); URL-safe compression (R11); helpers (R1,R2).
