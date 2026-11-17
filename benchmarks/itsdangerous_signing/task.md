# SEC-221: `itsdangerous` — cryptographically signed tokens for untrusted channels (Python library)

Build a Python package `itsdangerous` (Python >= 3.9, standard library only) that signs data so it can
be passed through untrusted channels (cookies, URLs, e-mails) and verified on the way back. It must be
**wire-compatible** with the widely deployed `itsdangerous` 2.x token format, so tokens issued by
existing services remain valid, and expose the same public API.

Public API (importable from the package root):
* `Signer(secret_key, salt=b"itsdangerous.Signer", sep=".", key_derivation="django-concat",
  digest_method=hashlib.sha1, algorithm=None)` with `sign(value) -> bytes`, `unsign(signed) -> bytes`,
  `validate(signed) -> bool`, `get_signature(value)`, `verify_signature(value, sig)`, `derive_key()`.
  `secret_key` may be str/bytes or a list of keys for rotation (newest last; sign with the newest,
  accept any). Key derivation modes: `"concat"` (digest(salt + key)), `"django-concat"`
  (digest(salt + b"signer" + key)), `"hmac"` (HMAC(key, salt)), `"none"` (key itself). Signature =
  URL-safe base64 **without padding** of HMAC(derived key, value). Token = `value + sep + signature`.
  Separator must not be a URL-safe base64 character (raise `ValueError`).
* `TimestampSigner` — token = `value . base64(timestamp as big-endian int, no padding) . signature`
  (signature covers value+sep+timestamp); `unsign(signed, max_age=None, return_timestamp=False)` and
  `validate(signed, max_age=None)`; `get_timestamp()` uses `int(time.time())`; returned timestamps are
  timezone-aware UTC `datetime`s.
* `Serializer(secret_key, salt=b"itsdangerous", serializer=json, signer=Signer, signer_kwargs=None,
  fallback_signers=None)` with `dumps/loads/dump/load/loads_unsafe/load_unsafe`; the default
  serializer is the standard `json` module with its default formatting (`json.dumps(obj)`, i.e. `", "`
  and `": "` separators). `TimedSerializer` (`loads(..., max_age=, return_timestamp=)`).
  `URLSafeSerializer` / `URLSafeTimedSerializer`: payload is compact JSON (`separators=(",", ":")`), zlib-compressed if that is
  shorter (then prefixed with `.`), URL-safe base64 encoded without padding.
* Exceptions: `BadData` → `BadSignature(message, payload)` → `BadTimeSignature(message, payload,
  date_signed)` → `SignatureExpired`; `BadSignature` → `BadHeader(message, payload, header,
  original_error)`; `BadData` → `BadPayload(message, original_error)`. Messages like
  `Signature b'...' does not match`, `No "." found in value`, `Signature age 15 > 10 seconds`.
* Helpers `want_bytes`, `base64_encode`, `base64_decode` (raise `BadData` on invalid input).
* Constant-time signature comparison.

Include a thorough pytest suite (known-answer vectors you compute from the format definition, tampering,
expiry, key rotation, every key-derivation mode, URL-safe compression) and a README.
