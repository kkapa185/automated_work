# Requirements: `itsdangerous` (SEC-221)

## Product
A pure-standard-library Python (>=3.9) package `itsdangerous` that signs bytes/objects for untrusted channels and verifies them later, wire-compatible with itsdangerous 2.x tokens. Library type; test strategy = pytest unit tests with known-answer vectors computed independently from the format definition (hashlib/hmac/base64 in the tests, never via the package).

## Module layout (from docs/*.rst `.. module::` directives)
`itsdangerous/{__init__,encoding,exc,signer,serializer,timed,url_safe}.py`; root re-exports the public API.

## Acceptance criteria
R1. `want_bytes(s, encoding="utf-8", errors="strict")`: str -> encoded bytes; bytes unchanged.
R2. `base64_encode(str|bytes)` = URL-safe base64, padding stripped, returns bytes. `base64_decode` accepts str/bytes, restores padding, raises `BadData("Invalid base64-encoded data")` on invalid input (bad length); like 2.x, non-ASCII/out-of-alphabet characters are ignored.
R3. `Signer(secret_key, salt=b"itsdangerous.Signer", sep=".", key_derivation="django-concat", digest_method=hashlib.sha1, algorithm=None)`; str/bytes salt/key accepted; secret_key may be a list (newest last); `secret_key` attribute holds list of bytes; `secret_keys` property; `default_digest_method`, `default_key_derivation` class attrs.
R4. Key derivation: concat=`digest(salt+key)`; django-concat=`digest(salt+b"signer"+key)`; hmac=`HMAC(key, salt, digest)`; none=key; other value -> `TypeError("Unknown key derivation method")`. `derive_key(secret_key=None)` uses newest key by default.
R5. Signature = urlsafe-b64 no padding of HMAC(derived key, value, digest_method). `algorithm` defaults to `HMACAlgorithm(digest_method)`; `NoneAlgorithm` yields empty signature and `verify_signature` is true only for empty sig; `SigningAlgorithm.get_signature/verify_signature` use constant-time compare (`hmac.compare_digest`).
R6. `sign(value)` = value + sep + signature (bytes). `unsign(signed)` returns value bytes; `BadSignature("No \"<sep>\" found in value")` if sep absent; `BadSignature("Signature b'<sig>' does not match", payload=value)` on mismatch; every key tried newest→oldest. `validate(signed)` -> bool. `get_signature(value)` -> bytes; `verify_signature(value, sig)` accepts str/bytes sig, bad base64 -> False, tries all keys.
R7. Separator in the URL-safe base64 alphabet (`A-Za-z0-9-_=`) -> `ValueError("The given separator cannot be used because it may be contained in the signature itself. ASCII letters, digits, and '-_=' must not be used.")`.
R8. Doc vectors: `Signer("secret-key").sign("my string")==b'my string.wh6tMHxLgJqB6oY1uT73iMlyrOA'`; unsign roundtrip; changed value raises BadSignature.
R9. `TimestampSigner`: token `value.<b64(int big-endian minimal bytes)>.<sig>`; signature covers `value+sep+timestamp`; `get_timestamp()=int(time.time())`; `timestamp_to_datetime(ts)` -> tz-aware UTC datetime. `unsign(signed, max_age=None, return_timestamp=False)`: bad signature first; missing timestamp -> `BadTimeSignature("timestamp missing", payload=value)`; undecodable timestamp -> `BadTimeSignature("Malformed timestamp", payload=value, date_signed=None)`; if max_age: age=now-ts; age>max_age -> `SignatureExpired("Signature age {age} > {max_age} seconds", payload=value, date_signed=dt)`; age<0 -> `SignatureExpired("Signature age {age} < 0 seconds", ...)`; `return_timestamp=True` returns `(value, datetime)`. `validate(signed, max_age=None)` -> bool. Timestamp 0 encodes as empty-bytes b64 (b"").
R10. `Serializer(secret_key, salt=b"itsdangerous", serializer=json, signer=Signer, signer_kwargs=None, fallback_signers=None)`; default json formatting (`json.dumps(obj)`, `", "` / `": "`); signer built as `signer(secret_keys, salt=salt, **signer_kwargs)` with no extra defaults. Methods: `dumps(obj, salt=None)`→ str if serializer is text else bytes (default JSON ⇒ `str`? see A1), `loads(s, salt=None)`, `dump/load` (file-like), `loads_unsafe/load_unsafe` → `(bool, obj|None)`, `load_payload`, `dump_payload`, `make_signer`, `iter_unsigners`. Doc vector: `Serializer("secret-key").dumps([1,2,3,4])=='[1, 2, 3, 4].r7R9RhGgDPvvWl3iNzLuIIfELmo'` and loads roundtrip.
R11. `fallback_signers` items: dict (kwargs), Signer class, or `(class, kwargs)`; tried after primary on BadSignature; last failure raised; docs example works. Class attrs `default_serializer`, `default_signer`, `default_fallback_signers`.
R12. Payload errors: loads_payload failure -> `BadPayload("Could not load the payload because an exception occurred on unserializing the data.", original_error=e)`; unsafe load returns `(False, payload-or-None)` on bad signature with decodable payload, `(False, None)` otherwise. 
R13. `TimedSerializer.loads(s, max_age=None, return_timestamp=False, salt=None)`; default signer `TimestampSigner`; `loads_unsafe` supports max_age.
R14. `URLSafeSerializer`: payload = compact JSON (`separators=(",",":")`), zlib-compress if result is shorter than raw (then prefix `.`), urlsafe-b64 no padding; loading reverses (leading `.` ⇒ decompress), errors -> `BadPayload` with message about decompress / base64. `URLSafeTimedSerializer` = Timed + URLSafe. Doc vectors: `URLSafeSerializer("secret-key").dumps([1,2,3,4])=='WzEsMiwzLDRd.wSPHqC0gR7VUqivlSukJ0IeTDgo'`; salt `activate` dumps(42)=='NDI.MHQqszw6Wc81wOBQszCrEE_RlzY', `upgrade` → 'NDI.c0MpsD6gzpilOAeUPra3NShPXsE'; cross-salt loads raises BadSignature.
R15. Exceptions: `BadData(message)` with `.message`, str is message; `BadSignature(message, payload=None)`; `BadTimeSignature(message, payload=None, date_signed=None)`; `SignatureExpired(BadTimeSignature)`; `BadHeader(message, payload=None, header=None, original_error=None)` subclass of BadSignature; `BadPayload(message, original_error=None)` subclass of BadData.
R16. Key rotation (docs example): token signed with oldest list works after rotation; signing uses newest key; removed key rejected.
R17. Signer/Serializer expose `Signer` doc exceptions: str/bytes inputs both accepted everywhere.
R18. Package root exports: Signer, TimestampSigner, Serializer, TimedSerializer, URLSafeSerializer, URLSafeTimedSerializer, BadData, BadSignature, BadTimeSignature, BadHeader, BadPayload, SignatureExpired, base64_encode, base64_decode, want_bytes, NoneAlgorithm, HMACAlgorithm, SigningAlgorithm, `__version__`.
R19. Packaging: `pyproject.toml` (no runtime deps; pytest as test extra), README, `pytest` passes from clean checkout.

## Assumptions
A1. Per the 2.x format, default JSON serializer is text-based, so `dumps` returns `str` (the doc's `b'[1, 2, 3, 4].…'` example is the older bytes form; the ticket's "sign(value) -> bytes" applies to Signer). Both docs shapes: signature/bytes content identical; tests assert `.encode()` equality too. `loads` accepts str or bytes.
A2. Docs' `Signature does not match` is shortened; ticket message `Signature b'...' does not match` is used.
A3. Docs reference `load_payload` (doc) — implemented as the unsigned-payload-decoding hook; `loads_payload` also provided as alias is NOT added (no extras).
A4. `Serializer(secret_key=None)` in docs fallback example is illustrative only; secret_key is required by the ticket signature, no default is invented... (None raises nothing special beyond Signer's handling).
A5. Timestamps are non-negative ints; negative ages report `< 0`.

## Test strategy
tests/test_encoding.py (R1,R2), test_signer.py (R3–R8, KATs with hashlib/hmac, all derivation modes, rotation, tampering, separators), test_timed.py (R9, time monkeypatched), test_serializer.py (R10–R12, R16), test_url_safe.py (R14, compression), test_exc.py (R15), test_api.py (R18). Doc examples are asserted verbatim.

A6. zlib compression is used when `len(compressed) < len(json)` (ticket wording: "if that is shorter").
A7. `Serializer`'s `serializer`/`signer` parameters default to `None`, resolved to the class attrs `default_serializer` (json) / `default_signer`.
