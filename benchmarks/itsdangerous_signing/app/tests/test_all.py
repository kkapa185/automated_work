import base64
import hashlib
import hmac
import json
import time
import zlib
from datetime import timezone

import pytest

import itsdangerous as i
from itsdangerous import encoding


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def hm(key, msg, d=hashlib.sha1):
    return hmac.new(key, msg, d).digest()


# ---- R1/R2 helpers
def test_want_bytes_r1():
    assert i.want_bytes("é") == "é".encode()
    assert i.want_bytes(b"x") == b"x"


def test_base64_r2():
    assert i.base64_encode("a?>") == b"YT8-"
    assert i.base64_encode(b"a") == b"YQ"
    assert i.base64_decode("YQ") == b"a"
    assert i.base64_decode(b"YT8-") == b"a?>"
    for bad in ("Y", "!!!!", "é"):
        with pytest.raises(i.BadData):
            i.base64_decode(bad)
    assert encoding.bytes_to_int(encoding.int_to_bytes(123456789)) == 123456789
    assert encoding.int_to_bytes(0) == b""


# ---- R3-R6 signer known answers
@pytest.mark.parametrize(
    "mode,derive",
    [
        ("concat", lambda s, k: hashlib.sha1(s + k).digest()),
        ("django-concat", lambda s, k: hashlib.sha1(s + b"signer" + k).digest()),
        ("hmac", lambda s, k: hm(k, s)),
        ("none", lambda s, k: k),
    ],
)
def test_key_derivation_r4(mode, derive):
    salt, key = b"itsdangerous.Signer", b"secret"
    s = i.Signer("secret", key_derivation=mode)
    assert s.derive_key() == derive(salt, key)
    expected = b"hello." + b64(hm(derive(salt, key), b"hello"))
    assert s.sign("hello") == expected
    assert s.unsign(expected) == b"hello"


def test_default_is_django_concat_and_sha256():
    s = i.Signer(b"k", salt=b"x", digest_method=hashlib.sha256)
    key = hashlib.sha256(b"x" + b"signer" + b"k").digest()
    assert s.sign(b"v") == b"v." + b64(hm(key, b"v", hashlib.sha256))


def test_unknown_derivation():
    with pytest.raises(TypeError):
        i.Signer("k", key_derivation="x").derive_key()


def test_sep_validation_r3():
    for sep in ("a", "Z", "5", "-", "_", "="):
        with pytest.raises(ValueError):
            i.Signer("k", sep=sep)
    s = i.Signer("k", sep=":")
    assert s.sign("a").startswith(b"a:")
    assert s.unsign(s.sign("a:b")) == b"a:b"


def test_unsign_errors_r6():
    s = i.Signer("k")
    with pytest.raises(i.BadSignature, match='No "." found in value'):
        s.unsign("nosep")
    tok = s.sign("v")
    bad = tok[:-2] + b"AA"
    with pytest.raises(i.BadSignature) as e:
        s.unsign(bad)
    assert e.value.payload == b"v"
    assert str(e.value) == f"Signature {bad.rsplit(b'.', 1)[1]!r} does not match"
    assert not s.validate(bad) and s.validate(tok)
    assert not s.verify_signature(b"v", "!!!")
    assert s.verify_signature("v", s.get_signature("v"))
    assert s.unsign(tok.decode()) == b"v"


def test_none_algorithm():
    s = i.Signer("k", algorithm=i.NoneAlgorithm())
    assert s.sign("v") == b"v."
    assert s.unsign(b"v.") == b"v"


def test_rotation_r12():
    old = i.Signer("old")
    tok = old.sign("v")
    rot = i.Signer(["old", "new"])
    assert rot.unsign(tok) == b"v"
    assert rot.sign("v") == i.Signer("new").sign("v")
    assert not i.Signer(["new", "old2"]).validate(tok)
    assert rot.secret_key == b"new"


# ---- R7 timestamp
def test_timestamp_known_answer(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1700000000.9)
    s = i.TimestampSigner("k")
    ts = b64((1700000000).to_bytes(4, "big"))
    key = hashlib.sha1(b"itsdangerous.Signer" + b"signer" + b"k").digest()
    assert s.sign("v") == b"v." + ts + b"." + b64(hm(key, b"v." + ts))
    v, dt = s.unsign(s.sign("v"), return_timestamp=True)
    assert v == b"v" and dt.tzinfo is timezone.utc and int(dt.timestamp()) == 1700000000


def test_timestamp_expiry(monkeypatch):
    now = [1000]
    monkeypatch.setattr(time, "time", lambda: now[0])
    s = i.TimestampSigner("k")
    tok = s.sign("v")
    now[0] = 1010
    assert s.unsign(tok, max_age=10) == b"v"
    now[0] = 1015
    with pytest.raises(i.SignatureExpired, match="Signature age 15 > 10 seconds") as e:
        s.unsign(tok, max_age=10)
    assert e.value.payload == b"v" and e.value.date_signed.year == 1970
    assert not s.validate(tok, max_age=10) and s.validate(tok)
    now[0] = 990
    with pytest.raises(i.SignatureExpired, match="< 0"):
        s.unsign(tok, max_age=10)


def test_timestamp_errors():
    s = i.TimestampSigner("k")
    plain = i.Signer("k").sign("nodots")
    with pytest.raises(i.BadTimeSignature, match="timestamp missing"):
        s.unsign(plain)
    mal = i.Signer("k").sign(b"v.!!!")
    with pytest.raises(i.BadTimeSignature, match="Malformed timestamp"):
        s.unsign(mal)
    with pytest.raises(i.BadSignature, match='No "."'):
        s.unsign("abc")
    tok = s.sign("v")
    bad = tok[:-2] + b"AA"
    with pytest.raises(i.BadTimeSignature) as e:
        s.unsign(bad)
    assert e.value.date_signed is not None and e.value.payload == b"v"


# ---- R8 exceptions
def test_exceptions_r8():
    assert issubclass(i.SignatureExpired, i.BadTimeSignature)
    assert issubclass(i.BadTimeSignature, i.BadSignature)
    assert issubclass(i.BadHeader, i.BadSignature)
    assert issubclass(i.BadPayload, i.BadData)
    assert not issubclass(i.BadPayload, i.BadSignature)
    h = i.BadHeader("m", b"p", {"a": 1}, ValueError())
    assert (h.message, h.payload, h.header) == ("m", b"p", {"a": 1}) and str(h) == "m"
    p = i.BadPayload("m", KeyError())
    assert isinstance(p.original_error, KeyError)


# ---- R9/R10 serializer
def test_serializer_known_answer():
    s = i.Serializer("k")
    payload = json.dumps({"a": [1, 2]})
    assert payload == '{"a": [1, 2]}'
    key = hm(b"k", b"itsdangerous")
    sig = b64(hm(key, payload.encode()))
    # signer salt is the serializer salt, derivation hmac
    expected = payload + "." + sig.decode()
    assert s.dumps({"a": [1, 2]}) == expected
    assert s.loads(expected) == {"a": [1, 2]}


def test_serializer_errors_and_unsafe():
    s = i.Serializer("k")
    tok = s.dumps([1])
    with pytest.raises(i.BadSignature):
        s.loads(tok[:-1] + ("A" if tok[-1] != "A" else "B"))
    with pytest.raises(i.BadSignature):
        s.loads(tok, salt="other")
    assert s.loads(s.dumps([1], salt="o"), salt="o") == [1]
    ok, d = s.loads_unsafe(tok)
    assert ok and d == [1]
    ok, d = s.loads_unsafe(tok[:-1] + ("A" if tok[-1] != "A" else "B"))
    assert not ok and d == [1]
    assert s.loads_unsafe("nodot") == (False, None)
    garbage = i.Signer("k", salt="itsdangerous", key_derivation="hmac").sign("{notjson")
    with pytest.raises(i.BadPayload):
        s.loads(garbage)
    assert s.loads_unsafe(garbage) == (False, None)


def test_dump_load_files(tmp_path):
    s = i.Serializer("k")
    f = tmp_path / "x"
    with open(f, "w") as fh:
        s.dump({"a": 1}, fh)
    with open(f) as fh:
        assert s.load(fh) == {"a": 1}
    with open(f) as fh:
        assert s.load_unsafe(fh) == (True, {"a": 1})


def test_serializer_rotation_and_fallback():
    old = i.Serializer("old")
    tok = old.dumps("x")
    assert i.Serializer(["old", "new"]).loads(tok) == "x"
    new = i.Serializer("new", fallback_signers=[{"key_derivation": "hmac"}])
    legacy = i.Serializer("new", signer_kwargs={"key_derivation": "concat"}).dumps(1)
    with pytest.raises(i.BadSignature):
        i.Serializer("new").loads(legacy)
    assert i.Serializer(
        "new", fallback_signers=[(i.Signer, {"key_derivation": "concat"})]
    ).loads(legacy) == 1
    assert new.loads(new.dumps(2)) == 2


def test_binary_serializer():
    import pickle

    s = i.Serializer("k", serializer=pickle)
    tok = s.dumps({"a": 1})
    assert isinstance(tok, bytes) and s.loads(tok) == {"a": 1}


def test_timed_serializer(monkeypatch):
    now = [5000]
    monkeypatch.setattr(time, "time", lambda: now[0])
    s = i.TimedSerializer("k")
    tok = s.dumps({"a": 1})
    now[0] = 5020
    assert s.loads(tok, max_age=30) == {"a": 1}
    obj, dt = s.loads(tok, max_age=30, return_timestamp=True)
    assert int(dt.timestamp()) == 5000
    with pytest.raises(i.SignatureExpired):
        s.loads(tok, max_age=10)
    assert s.loads_unsafe(tok, max_age=10) == (False, {"a": 1})
    assert s.loads_unsafe(tok) == (True, {"a": 1})


# ---- R11 url safe
def test_urlsafe_plain_and_compressed():
    s = i.URLSafeSerializer("k")
    small = s.dumps({"a": 1})
    body = small.rsplit(".", 1)[0]
    assert base64.urlsafe_b64decode(body + "==") == b'{"a":1}'
    big = {"k": "x" * 200}
    tok = s.dumps(big)
    assert tok.startswith(".")
    body = tok[1:].rsplit(".", 1)[0]
    raw = zlib.decompress(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert raw == json.dumps(big, separators=(",", ":")).encode()
    assert s.loads(tok) == big and s.loads(small) == {"a": 1}
    assert "=" not in tok


def test_urlsafe_bad_payload():
    sg = i.Signer("k", salt="itsdangerous", key_derivation="hmac")
    s = i.URLSafeSerializer("k")
    with pytest.raises(i.BadPayload):
        s.loads(sg.sign("!!!"))
    with pytest.raises(i.BadPayload):
        s.loads(sg.sign("." + b64(b"notzlib").decode()))
    with pytest.raises(i.BadSignature):
        s.loads(s.dumps(1) + "x")


def test_urlsafe_timed(monkeypatch):
    now = [100]
    monkeypatch.setattr(time, "time", lambda: now[0])
    s = i.URLSafeTimedSerializer("k")
    tok = s.dumps([1, 2, 3])
    now[0] = 200
    assert s.loads(tok, max_age=100) == [1, 2, 3]
    with pytest.raises(i.SignatureExpired):
        s.loads(tok, max_age=99)


# ---- R13 / R15
def test_constant_time_compare_r13(monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    s = i.Signer("k")
    assert s.validate(s.sign("v"))
    assert calls


def test_package_r15():
    assert i.__version__.startswith("2.")
    for name in i.__all__:
        assert hasattr(i, name)


def test_timestamp_no_padding_and_large(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 2**33 + 5)
    s = i.TimestampSigner("k")
    tok = s.sign("v")
    assert b"=" not in tok
    assert s.unsign(tok, return_timestamp=True)[0] == b"v"
