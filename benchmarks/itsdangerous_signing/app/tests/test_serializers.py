import hashlib
import io
import json
import zlib
from datetime import datetime, timezone

import pytest

from itsdangerous import (BadPayload, BadSignature, BadTimeSignature,
                          Serializer, Signer, SignatureExpired,
                          TimedSerializer, TimestampSigner, URLSafeSerializer,
                          URLSafeTimedSerializer)

import kat


# ---- Serializer -----------------------------------------------------------
def test_r10_doc_example():
    s = Serializer("secret-key")
    t = s.dumps([1, 2, 3, 4])
    assert t == "[1, 2, 3, 4].r7R9RhGgDPvvWl3iNzLuIIfELmo"
    assert s.loads("[1, 2, 3, 4].r7R9RhGgDPvvWl3iNzLuIIfELmo") == [1, 2, 3, 4]
    assert s.loads(t.encode()) == [1, 2, 3, 4]


def test_r10_known_answer_default_json_format():
    obj = {"a": [1, 2], "b": None}
    payload = json.dumps(obj).encode()
    assert payload == b'{"a": [1, 2], "b": null}'
    assert Serializer("k").dumps(obj).encode() == kat.sign(payload, b"k", b"itsdangerous")


def test_r10_plain_serializer_uses_signer_defaults():
    s = Serializer("k")
    sg = s.make_signer()
    assert isinstance(sg, Signer) and not isinstance(sg, TimestampSigner)
    assert sg.salt == b"itsdangerous" and sg.key_derivation == "django-concat"
    assert sg.digest_method is hashlib.sha1 and sg.sep == b"."


def test_r10_signer_kwargs_passed_exactly():
    seen = {}

    class Spy(Signer):
        def __init__(self, *a, **kw):
            seen["a"], seen["kw"] = a, kw
            super().__init__(*a, **kw)

    Serializer("k", signer=Spy).dumps(1)
    assert seen["kw"] == {"salt": b"itsdangerous"}
    Serializer("k", signer=Spy, signer_kwargs={"sep": "!"}).dumps(1)
    assert seen["kw"] == {"salt": b"itsdangerous", "sep": "!"}
    assert seen["a"] == ([b"k"],)


def test_r10_signer_kwargs_applied():
    s = Serializer("k", signer_kwargs={"key_derivation": "hmac", "sep": ":",
                                        "digest_method": hashlib.sha256})
    expected = kat.sign(b"[1]", b"k", b"itsdangerous", b":", mode="hmac", digest=hashlib.sha256)
    assert s.dumps([1]).encode() == expected
    assert s.loads(expected) == [1]


def test_r10_salt_override_and_context_separation():
    s = Serializer("k")
    t = s.dumps(5, salt="other")
    assert t.encode() == kat.sign(b"5", b"k", b"other")
    assert s.loads(t, salt="other") == 5
    with pytest.raises(BadSignature):
        s.loads(t)


def test_r14_doc_salts():
    s1 = URLSafeSerializer("secret-key", salt="activate")
    s2 = URLSafeSerializer("secret-key", salt="upgrade")
    assert s1.dumps(42) == "NDI.MHQqszw6Wc81wOBQszCrEE_RlzY"
    assert s2.dumps(42) == "NDI.c0MpsD6gzpilOAeUPra3NShPXsE"
    with pytest.raises(BadSignature):
        s2.loads(s1.dumps(42))
    assert s2.loads(s2.dumps(42)) == 42


def test_r10_dump_load_files():
    s = Serializer("k")
    f = io.StringIO()
    s.dump({"x": 1}, f)
    assert f.getvalue() == s.dumps({"x": 1})
    f.seek(0)
    assert s.load(f) == {"x": 1}
    f.seek(0)
    assert s.load_unsafe(f) == (True, {"x": 1})
    bf = io.BytesIO(s.dumps([1]).encode())
    assert s.load(bf) == [1]


def test_r12_loads_unsafe():
    s = Serializer("k")
    t = s.dumps({"a": 1})
    assert s.loads_unsafe(t) == (True, {"a": 1})
    tampered = t[:-1] + ("A" if t[-1] != "A" else "B")
    assert s.loads_unsafe(tampered) == (False, {"a": 1})
    assert s.loads_unsafe("nosep") == (False, None)
    assert s.loads_unsafe("notjson.AAAA") == (False, None)


def test_r12_bad_payload():
    sg = Signer("k", salt="itsdangerous")
    with pytest.raises(BadPayload) as ei:
        Serializer("k").loads(sg.sign(b"{not json"))
    assert ei.value.message == (
        "Could not load the payload because an exception occurred on unserializing the data."
    )
    assert isinstance(ei.value.original_error, ValueError)
    with pytest.raises(BadPayload):
        Serializer("k").loads(sg.sign(b"\xff\xfe"))  # invalid utf-8


def test_r12_load_payload_exposed_on_failure():
    s = Serializer("k")
    t = s.dumps([1, 2])
    bad = t[:-1] + ("A" if t[-1] != "A" else "B")
    with pytest.raises(BadSignature) as ei:
        s.loads(bad)
    assert s.load_payload(ei.value.payload) == [1, 2]


def test_r10_custom_binary_serializer():
    class Rev:
        @staticmethod
        def dumps(o):
            return repr(o).encode()[::-1]

        @staticmethod
        def loads(b):
            return b[::-1].decode()

    s = Serializer("k", serializer=Rev)
    t = s.dumps([1])
    assert isinstance(t, bytes)
    assert s.loads(t) == "[1]"


def test_r16_rotation_doc():
    keys = ["2b9cd98e", "169d7886", "b6af09f5"]
    s = Serializer(keys)
    t = s.dumps({"id": 42})
    assert t.encode() == kat.sign(b'{"id": 42}', b"b6af09f5", b"itsdangerous")
    keys.append("cf9b3588")
    del keys[0]
    assert Serializer(keys).loads(t) == {"id": 42}
    with pytest.raises(BadSignature):
        Serializer(["zzz"]).loads(t)


def test_r11_fallback_signers_doc_example():
    old = Serializer("k", signer_kwargs={"digest_method": hashlib.sha1}).dumps([1])
    s = Serializer(
        "k",
        signer_kwargs={"digest_method": hashlib.sha512},
        fallback_signers=[{"digest_method": hashlib.sha1}],
    )
    assert s.loads(old) == [1]
    new = s.dumps([1])
    assert new.encode() == kat.sign(b"[1]", b"k", b"itsdangerous", digest=hashlib.sha512)
    assert len(new) > len(old)
    assert Serializer("k", signer_kwargs={"digest_method": hashlib.sha512}).loads(new) == [1]
    with pytest.raises(BadSignature):  # without fallback, sha1 token is invalid
        Serializer("k", signer_kwargs={"digest_method": hashlib.sha512}).loads(old)


def test_r11_fallback_forms():
    class MySigner(Signer):
        default_key_derivation = "concat"

    old = Serializer("k", signer=MySigner).dumps(1)
    # class form: uses serializer signer_kwargs
    assert Serializer("k", fallback_signers=[MySigner]).loads(old) == 1
    # tuple form
    assert Serializer("k", fallback_signers=[(MySigner, {})]).loads(old) == 1
    # dict form
    hm = Serializer("k", signer_kwargs={"key_derivation": "hmac"}).dumps(1)
    assert Serializer("k", fallback_signers=[{"key_derivation": "hmac"}]).loads(hm) == 1
    # all fail -> BadSignature
    with pytest.raises(BadSignature):
        Serializer("x", fallback_signers=[{"key_derivation": "hmac"}]).loads(hm)


def test_r11_iter_unsigners_order():
    s = Serializer("k", fallback_signers=[{"sep": "!"}, {"sep": ":"}])
    seps = [u.sep for u in s.iter_unsigners()]
    assert seps == [b".", b"!", b":"]


# ---- Timed -----------------------------------------------------------------
@pytest.fixture
def clock(monkeypatch):
    state = {"now": 1700000000}
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: state["now"])
    return state


def test_r13_timed_serializer(clock):
    s = TimedSerializer("k")
    t = s.dumps([1])
    assert t.encode() == kat.sign_ts(b"[1]", 1700000000, b"k", b"itsdangerous")
    assert s.loads(t, max_age=10) == [1]
    obj, dt = s.loads(t, return_timestamp=True)
    assert obj == [1] and dt == datetime.fromtimestamp(1700000000, tz=timezone.utc)
    clock["now"] += 11
    with pytest.raises(SignatureExpired) as ei:
        s.loads(t, max_age=10)
    assert ei.value.message == "Signature age 11 > 10 seconds"
    assert s.loads(t) == [1]


def test_r13_timed_unsafe(clock):
    s = TimedSerializer("k")
    t = s.dumps({"a": 1})
    assert s.loads_unsafe(t, max_age=100) == (True, {"a": 1})
    clock["now"] += 500
    ok, obj = s.loads_unsafe(t, max_age=100)
    assert (ok, obj) == (False, {"a": 1})
    tampered = t[:-1] + ("A" if t[-1] != "A" else "B")
    assert s.loads_unsafe(tampered) == (False, {"a": 1})


def test_r13_timed_rotation_and_bad_sig(clock):
    t = TimedSerializer(["a", "b"]).dumps(1)
    assert TimedSerializer(["b", "c"]).loads(t) == 1
    with pytest.raises(BadTimeSignature):
        TimedSerializer("zzz").loads(t)
    with pytest.raises(BadSignature):
        TimedSerializer("k").loads("nosep")


# ---- URL-safe ----------------------------------------------------------------
def test_r14_doc_example():
    s = URLSafeSerializer("secret-key")
    assert s.dumps([1, 2, 3, 4]) == "WzEsMiwzLDRd.wSPHqC0gR7VUqivlSukJ0IeTDgo"
    assert s.loads("WzEsMiwzLDRd.wSPHqC0gR7VUqivlSukJ0IeTDgo") == [1, 2, 3, 4]


def test_r14_compact_json_known_answer():
    obj = {"a": [1, 2], "b": "x"}
    raw = json.dumps(obj, separators=(",", ":")).encode()
    assert raw == b'{"a":[1,2],"b":"x"}'
    assert URLSafeSerializer("k").dumps(obj).encode() == kat.sign(
        kat.b64(raw), b"k", b"itsdangerous")


def test_r14_compression():
    obj = {"data": "a" * 500, "n": list(range(50))}
    raw = json.dumps(obj, separators=(",", ":")).encode()
    comp = zlib.compress(raw)
    assert len(comp) < len(raw)
    t = URLSafeSerializer("k").dumps(obj)
    assert t.startswith(".")
    assert t.encode() == kat.sign(b"." + kat.b64(comp), b"k", b"itsdangerous")
    assert URLSafeSerializer("k").loads(t) == obj


def test_r14_not_compressed_when_not_shorter():
    s = URLSafeSerializer("k")
    for obj in ([1, 2, 3], "x", {"a": 1}, 42, None):
        t = s.dumps(obj)
        assert not t.startswith(".")
        assert s.loads(t) == obj


def test_r14_output_charset_and_unicode():
    obj = {"emoji": "héllo ☃" * 3, "v": [1.5, True, None]}
    t = URLSafeSerializer("k").dumps(obj)
    assert set(t) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.")
    assert "=" not in t
    assert URLSafeSerializer("k").loads(t) == obj


def test_r14_bad_payloads():
    sg = Signer("k", salt="itsdangerous")
    s = URLSafeSerializer("k")
    with pytest.raises(BadPayload) as ei:
        s.loads(sg.sign(b"A"))  # invalid base64 length
    assert "base64" in ei.value.message
    with pytest.raises(BadPayload) as ei:
        s.loads(sg.sign(b"." + kat.b64(b"not zlib")))
    assert "decompress" in ei.value.message
    with pytest.raises(BadPayload):
        s.loads(sg.sign(kat.b64(b"{bad")))


def test_r14_unsafe_and_payload_roundtrip():
    s = URLSafeSerializer("k")
    obj = {"x": "y" * 300}
    t = s.dumps(obj)
    bad = t[:-1] + ("A" if t[-1] != "A" else "B")
    assert s.loads_unsafe(bad) == (False, obj)


def test_r14_timed(clock):
    s = URLSafeTimedSerializer("k")
    t = s.dumps([1, 2, 3, 4])
    body = b"WzEsMiwzLDRd." + kat.b64(kat.ts_bytes(1700000000))
    assert t.encode() == body + b"." + kat.signature(body, b"k", b"itsdangerous")
    assert s.loads(t, max_age=5) == [1, 2, 3, 4]
    clock["now"] += 6
    with pytest.raises(SignatureExpired):
        s.loads(t, max_age=5)
    obj, dt = s.loads(t, return_timestamp=True)
    assert obj == [1, 2, 3, 4] and dt.year == 2023
    assert s.loads_unsafe(t, max_age=5) == (False, [1, 2, 3, 4])
