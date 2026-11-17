import base64
import hashlib
import hmac
import io
import json
import zlib
from datetime import datetime, timezone

import pytest

import itsdangerous as its
from itsdangerous import (
    BadData, BadHeader, BadPayload, BadSignature, BadTimeSignature, SignatureExpired,
    Serializer, Signer, TimedSerializer, TimestampSigner, URLSafeSerializer,
    URLSafeTimedSerializer, base64_decode, base64_encode, want_bytes,
)


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def sig(key, value, digest=hashlib.sha1):
    return b64(hmac.new(key, value, digest).digest())


# ---------- R1/R2 helpers
def test_r1_want_bytes():
    assert want_bytes("é") == "é".encode()
    assert want_bytes(b"x") == b"x"


def test_r2_base64():
    assert base64_encode(b"a") == b"YQ"
    assert base64_encode("abc?>") == b64(b"abc?>")
    assert base64_decode("YQ") == b"a"
    assert base64_decode(b"YQ==") == b"a"
    assert base64_decode(base64_encode(b"\xff\xfe\xfd")) == b"\xff\xfe\xfd"
    with pytest.raises(BadData) as e:
        base64_decode("a")  # impossible length
    assert e.value.message == "Invalid base64-encoded data"
    with pytest.raises(BadData):
        base64_decode(b"\xff\xfe")


# ---------- R3/R4/R5 Signer
KEY = b"secret-key"
SALT = b"itsdangerous.Signer"


def test_r4_known_answers_all_modes():
    v = b"hello"
    derived = {
        "concat": hashlib.sha1(SALT + KEY).digest(),
        "django-concat": hashlib.sha1(SALT + b"signer" + KEY).digest(),
        "hmac": hmac.new(KEY, SALT, hashlib.sha1).digest(),
        "none": KEY,
    }
    for mode, dk in derived.items():
        s = Signer(KEY, key_derivation=mode)
        assert s.derive_key() == dk
        assert s.sign(v) == v + b"." + sig(dk, v)
        assert s.unsign(s.sign(v)) == v


def test_r4_modes_differ_and_unknown_mode():
    sigs = {Signer(KEY, key_derivation=m).sign(b"x") for m in ("concat", "django-concat", "hmac", "none")}
    assert len(sigs) == 4
    with pytest.raises(TypeError):
        Signer(KEY, key_derivation="bogus").derive_key()


def test_r5_default_is_django_concat_sha1():
    dk = hashlib.sha1(SALT + b"signer" + KEY).digest()
    assert Signer(KEY).sign("v") == b"v." + sig(dk, b"v")


def test_r5_digest_method_and_salt_sep():
    s = Signer("k", salt="s", sep="!", digest_method=hashlib.sha256)
    dk = hashlib.sha256(b"s" + b"signer" + b"k").digest()
    assert s.sign(b"v") == b"v!" + sig(dk, b"v", hashlib.sha256)
    assert s.unsign("v!" + sig(dk, b"v", hashlib.sha256).decode()) == b"v"


def test_r3_bad_separator():
    for sep in ("a", "Z", "5", "-", "_"):
        with pytest.raises(ValueError):
            Signer("k", sep=sep)
    Signer("k", sep=":")


def test_r6_errors_and_tamper():
    s = Signer(KEY)
    with pytest.raises(BadSignature) as e:
        s.unsign(b"nodot")
    assert e.value.message == "No b'.' found in value"
    signed = s.sign(b"payload")
    with pytest.raises(BadSignature) as e:
        s.unsign(signed.replace(b"payload", b"payloaD"))
    assert e.value.payload == b"payloaD"
    assert e.value.message.startswith("Signature b'") and e.value.message.endswith("' does not match")
    assert str(e.value) == e.value.message
    assert not s.validate(signed[:-1] + (b"A" if signed[-1:] != b"A" else b"B"))
    assert not s.validate(b"abc.!!!")
    assert s.validate(signed) and s.validate(signed.decode())
    assert not Signer("other").validate(signed)
    assert not Signer(KEY, salt="x").validate(signed)


def test_r5_verify_get_signature():
    s = Signer(KEY)
    assert s.verify_signature("v", s.get_signature("v"))
    assert not s.verify_signature("v", "bad")
    assert s.get_signature(b"v") == sig(s.derive_key(), b"v")


def test_r3_key_rotation():
    old = Signer("old")
    new = Signer(["old", "new"])
    assert new.unsign(old.sign(b"x")) == b"x"
    assert new.sign(b"x") == Signer("new").sign(b"x")
    assert not Signer("new").validate(old.sign(b"x"))
    assert new.derive_key() == Signer("new").derive_key()
    assert new.derive_key("old") == old.derive_key()


def test_r3_salt_none_default_str_key():
    assert Signer("k", salt=None).sign("a") == Signer(b"k").sign(b"a")


def test_none_algorithm():
    s = Signer("k", algorithm=its.NoneAlgorithm())
    assert s.sign(b"a") == b"a."
    assert s.unsign(b"a.") == b"a"


# ---------- R7 TimestampSigner
class FakeTS(TimestampSigner):
    now = 1_700_000_000

    def get_timestamp(self):
        return type(self).now


def test_r7_format_and_known_answer():
    s = FakeTS(KEY)
    ts = b64((1_700_000_000).to_bytes(4, "big"))
    dk = s.derive_key()
    assert s.sign(b"v") == b"v." + ts + b"." + sig(dk, b"v." + ts)
    assert s.unsign(s.sign(b"v")) == b"v"


def test_r7_timestamp_minimal_encoding():
    class Z(FakeTS):
        now = 0
    assert Z(KEY).sign(b"v").split(b".")[1] == b""
    assert Z(KEY).unsign(Z(KEY).sign(b"v")) == b"v"
    class S(FakeTS):
        now = 256
    assert S(KEY).sign(b"v").split(b".")[1] == b64(b"\x01\x00")


def test_r7_return_timestamp_aware():
    s = FakeTS(KEY)
    v, dt = s.unsign(s.sign(b"v"), return_timestamp=True)
    assert v == b"v"
    assert dt == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
    assert dt.tzinfo is not None and dt.utcoffset().total_seconds() == 0


def test_r7_expiry_boundaries():
    s = FakeTS(KEY)
    token = s.sign(b"v")
    FakeTS.now += 10
    try:
        assert s.unsign(token, max_age=10) == b"v"
        assert s.validate(token, max_age=10)
        FakeTS.now += 5
        with pytest.raises(SignatureExpired) as e:
            s.unsign(token, max_age=10)
        assert e.value.message == "Signature age 15 > 10 seconds"
        assert e.value.payload == b"v"
        assert e.value.date_signed == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
        assert not s.validate(token, max_age=10)
        assert s.unsign(token) == b"v"
        assert isinstance(e.value, BadTimeSignature) and isinstance(e.value, BadSignature)
    finally:
        FakeTS.now = 1_700_000_000


def test_r7_future_timestamp():
    s = FakeTS(KEY)
    token = s.sign(b"v")
    FakeTS.now -= 5
    try:
        with pytest.raises(SignatureExpired) as e:
            s.unsign(token, max_age=10)
        assert e.value.message == "Signature age -5 < 0 seconds"
    finally:
        FakeTS.now = 1_700_000_000


def test_r7_errors():
    s = TimestampSigner(KEY)
    token = s.sign(b"v")
    with pytest.raises(BadTimeSignature) as e:
        s.unsign(token[:-2] + b"xx")
    assert e.value.payload == b"v"
    assert e.value.date_signed is not None
    with pytest.raises(BadSignature):
        s.unsign(b"nodots")
    # signed by plain Signer: valid signature, no timestamp
    plain = Signer(KEY).sign(b"nots")
    with pytest.raises(BadTimeSignature) as e:
        s.unsign(plain)
    assert e.value.message == "timestamp missing"
    # malformed timestamp with valid signature
    bad = Signer(KEY).sign(b"v.!!!")
    with pytest.raises(BadTimeSignature) as e:
        s.unsign(bad)
    assert e.value.message == "Malformed timestamp"
    assert not s.validate(b"junk")


def test_r7_real_clock_default():
    s = TimestampSigner(KEY)
    assert s.validate(s.sign("x"), max_age=5)


# ---------- R8 exceptions
def test_r8_exceptions():
    assert issubclass(BadSignature, BadData) and issubclass(BadHeader, BadSignature)
    assert issubclass(BadPayload, BadData) and not issubclass(BadPayload, BadSignature)
    assert issubclass(SignatureExpired, BadTimeSignature)
    err = RuntimeError("x")
    h = BadHeader("m", payload=b"p", header=b"h", original_error=err)
    assert (h.message, h.payload, h.header, h.original_error) == ("m", b"p", b"h", err)
    p = BadPayload("m", original_error=err)
    assert p.original_error is err and str(p) == "m"
    d = BadTimeSignature("m", b"p", datetime(2020, 1, 1))
    assert d.date_signed.year == 2020 and d.payload == b"p"
    assert BadSignature("m").payload is None


# ---------- R9/R12 Serializer
def test_r12_known_answer_default_serializer():
    s = Serializer(KEY)
    token = s.dumps({"a": [1, 2], "b": "é"})
    body = '{"a":[1,2],"b":"é"}'.encode()
    dk = hashlib.sha1(b"itsdangerous" + b"signer" + KEY).digest()
    assert token == (body + b"." + sig(dk, body)).decode()
    assert isinstance(token, str)
    assert s.loads(token) == {"a": [1, 2], "b": "é"}
    assert s.loads(token.encode()) == {"a": [1, 2], "b": "é"}


def test_r9_salt_override_and_tamper():
    s = Serializer(KEY)
    t = s.dumps([1], salt="x")
    assert s.loads(t, salt="x") == [1]
    with pytest.raises(BadSignature):
        s.loads(t)
    with pytest.raises(BadSignature):
        s.loads(t + "a", salt="x")
    assert Serializer(KEY, salt="x").loads(t) == [1]


def test_r9_file_api():
    s = Serializer(KEY)
    f = io.StringIO()
    s.dump({"k": 1}, f)
    f.seek(0)
    assert s.load(f) == {"k": 1}
    f.seek(0)
    assert s.load_unsafe(f) == (True, {"k": 1})


def test_r9_unsafe():
    s = Serializer(KEY)
    t = s.dumps({"k": 1})
    assert s.loads_unsafe(t) == (True, {"k": 1})
    assert s.loads_unsafe(t[:-1] + ("A" if t[-1] != "A" else "B")) == (False, {"k": 1})
    assert s.loads_unsafe("nodots") == (False, None)
    bad = Signer(KEY, salt="itsdangerous").sign(b"{notjson")
    with pytest.raises(BadPayload):
        s.loads_unsafe(bad)  # valid signature, undecodable payload
    assert s.loads_unsafe(b"{notjson.AAAA") == (False, None)


def test_r9_bad_payload():
    s = Serializer(KEY)
    token = Signer(KEY, salt="itsdangerous").sign(b"{notjson")
    with pytest.raises(BadPayload) as e:
        s.loads(token)
    assert e.value.original_error is not None
    token = Signer(KEY, salt="itsdangerous").sign(b"\xff\xfe")
    with pytest.raises(BadPayload):
        s.loads(token)


def test_r9_rotation_and_fallback():
    old = Serializer("old")
    new = Serializer(["old", "new"])
    assert new.loads(old.dumps(1)) == 1
    legacy = Serializer(KEY, signer_kwargs={"key_derivation": "hmac", "digest_method": hashlib.sha256})
    token = legacy.dumps("hi")
    with pytest.raises(BadSignature):
        Serializer(KEY).loads(token)
    for fb in (
        [{"key_derivation": "hmac", "digest_method": hashlib.sha256}],
        [(Signer, {"key_derivation": "hmac", "digest_method": hashlib.sha256})],
    ):
        assert Serializer(KEY, fallback_signers=fb).loads(token) == "hi"
    # new tokens use primary signer
    assert Serializer(KEY, fallback_signers=fb).dumps("hi") == Serializer(KEY).dumps("hi")


def test_r9_binary_serializer():
    import pickle
    s = Serializer(KEY, serializer=pickle)
    assert not s.is_text_serializer
    t = s.dumps({"x": 1})
    assert isinstance(t, bytes)
    assert s.loads(t) == {"x": 1}


def test_r9_custom_signer_kwargs():
    s = Serializer(KEY, signer_kwargs={"key_derivation": "none", "sep": "!"})
    t = s.dumps(1)
    assert "!" in t and s.loads(t) == 1


# ---------- R10 TimedSerializer
def test_r10_timed():
    s = TimedSerializer(KEY)
    t = s.dumps({"a": 1})
    assert s.loads(t, max_age=100) == {"a": 1}
    p, dt = s.loads(t, return_timestamp=True)
    assert p == {"a": 1} and dt.tzinfo is timezone.utc
    assert t.count(".") == 2
    assert isinstance(s.make_signer(), TimestampSigner)
    assert s.loads_unsafe(t) == (True, {"a": 1})


def test_r10_expired(monkeypatch):
    import time
    s = TimedSerializer(KEY)
    t = s.dumps(1)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 30)
    with pytest.raises(SignatureExpired):
        s.loads(t, max_age=10)
    assert s.loads_unsafe(t, max_age=10) == (False, 1)
    assert s.loads(t, max_age=60) == 1


# ---------- R11 URL safe
def test_r11_short_not_compressed():
    s = URLSafeSerializer(KEY)
    t = s.dumps([1, 2])
    payload = t.split(".")[0]
    assert base64_decode(payload) == b"[1,2]"
    assert s.loads(t) == [1, 2]


def test_r11_compressed():
    s = URLSafeSerializer(KEY)
    data = {"k": "a" * 500}
    t = s.dumps(data)
    assert t.startswith(".")
    body = t[1:].split(".")[0]
    raw = json.dumps(data, separators=(",", ":")).encode()
    assert zlib.decompress(base64_decode(body)) == raw
    assert len(t) < len(raw)
    assert s.loads(t) == data
    dk = hashlib.sha1(b"itsdangerous" + b"signer" + KEY).digest()
    payload = t.rsplit(".", 1)[0].encode()
    assert t.rsplit(".", 1)[1].encode() == sig(dk, payload)


def test_r11_no_padding_urlsafe_chars():
    s = URLSafeSerializer(KEY)
    t = s.dumps("???>>>~~~")
    assert "=" not in t and "+" not in t and "/" not in t


def test_r11_bad_payloads():
    s = URLSafeSerializer(KEY)
    sg = Signer(KEY, salt="itsdangerous")
    with pytest.raises(BadPayload):
        s.loads(sg.sign(b"!!!!"))
    with pytest.raises(BadPayload):
        s.loads(sg.sign(b"." + base64_encode(b"not zlib")))
    with pytest.raises(BadPayload):
        s.loads(sg.sign(base64_encode(b"{bad")))
    assert s.loads_unsafe("!!!!.AAAA") == (False, None)


def test_r11_timed():
    s = URLSafeTimedSerializer(KEY)
    data = ["x" * 300]
    t = s.dumps(data)
    assert t.startswith(".") and t.count(".") == 3
    assert s.loads(t, max_age=10) == data
    assert s.loads(t, return_timestamp=True)[0] == data
    with pytest.raises(BadSignature):
        URLSafeTimedSerializer("other").loads(t)


def test_public_api_exports():
    for name in its.__all__:
        assert hasattr(its, name)


def test_signature_positional_order():
    """Positional order: secret_key, salt, serializer, signer, signer_kwargs, fallback_signers."""
    import json as _json
    s = Serializer(KEY, b"salt", _json, Signer, {"sep": "!"}, [])
    assert "!" in s.dumps(1)
    assert Signer(KEY, b"s", ".", "concat", hashlib.sha256).key_derivation == "concat"
    t = TimedSerializer(KEY, b"salt", _json, TimestampSigner)
    assert t.loads(t.dumps([1])) == [1]
