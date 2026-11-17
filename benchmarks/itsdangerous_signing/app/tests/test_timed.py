from datetime import datetime, timezone

import pytest

from itsdangerous import (BadSignature, BadTimeSignature, SignatureExpired,
                          TimestampSigner, base64_encode)

import kat

NOW = 1700000000


@pytest.fixture
def clock(monkeypatch):
    state = {"now": NOW}
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: state["now"])
    return state


def test_r9_known_answer(clock):
    s = TimestampSigner("k")
    t = s.sign("foo")
    assert t == kat.sign_ts(b"foo", NOW, b"k")
    assert t.split(b".")[1] == kat.b64(NOW.to_bytes(4, "big"))
    assert s.unsign(t) == b"foo"


def test_r9_timestamp_minimal_big_endian(clock):
    clock["now"] = 258
    t = TimestampSigner("k").sign("v")
    assert t.split(b".")[1] == base64_encode(b"\x01\x02")
    clock["now"] = 0
    t = TimestampSigner("k").sign("v")
    assert t == kat.sign_ts(b"v", 0, b"k")
    assert t.split(b".")[1] == b""
    assert TimestampSigner("k").unsign(t) == b"v"


def test_r9_real_clock():
    import time
    before = int(time.time())
    s = TimestampSigner("k")
    v, dt = s.unsign(s.sign("x"), return_timestamp=True)
    assert before <= dt.timestamp() <= time.time() + 1
    assert s.get_timestamp() >= before


def test_r9_return_timestamp_utc(clock):
    s = TimestampSigner("k")
    v, dt = s.unsign(s.sign("foo"), return_timestamp=True)
    assert v == b"foo"
    assert dt == datetime.fromtimestamp(NOW, tz=timezone.utc)
    assert dt.tzinfo is not None and dt.utcoffset().total_seconds() == 0


def test_r9_expiry_messages(clock):
    s = TimestampSigner("k")
    t = s.sign("foo")
    clock["now"] = NOW + 15
    with pytest.raises(SignatureExpired) as ei:
        s.unsign(t, max_age=5)
    assert ei.value.message == "Signature age 15 > 5 seconds"
    assert ei.value.payload == b"foo"
    assert ei.value.date_signed == datetime.fromtimestamp(NOW, tz=timezone.utc)
    assert s.unsign(t, max_age=15) == b"foo"  # boundary is allowed
    assert s.unsign(t) == b"foo"  # no max_age -> never expires
    clock["now"] = NOW - 3
    with pytest.raises(SignatureExpired) as ei:
        s.unsign(t, max_age=10)
    assert ei.value.message == "Signature age -3 < 0 seconds"
    assert s.unsign(t) == b"foo"


def test_r9_max_age_zero(clock):
    s = TimestampSigner("k")
    t = s.sign("foo")
    assert s.unsign(t, max_age=0) == b"foo"
    clock["now"] += 1
    with pytest.raises(SignatureExpired):
        s.unsign(t, max_age=0)


def test_r9_validate(clock):
    s = TimestampSigner("k")
    t = s.sign("foo")
    assert s.validate(t)
    assert s.validate(t, max_age=1)
    clock["now"] += 100
    assert not s.validate(t, max_age=1)
    assert s.validate(t)
    assert not s.validate(b"garbage")


def test_r9_bad_signature_carries_payload_and_date(clock):
    s = TimestampSigner("k")
    t = s.sign("foo")
    bad = t[:-2] + (b"AA" if not t.endswith(b"AA") else b"BB")
    with pytest.raises(BadTimeSignature) as ei:
        s.unsign(bad)
    e = ei.value
    assert e.payload == b"foo"
    assert e.date_signed == datetime.fromtimestamp(NOW, tz=timezone.utc)
    assert e.message.startswith("Signature b'") and e.message.endswith("does not match")
    # signature is checked before expiry
    clock["now"] += 100
    with pytest.raises(BadTimeSignature) as ei:
        s.unsign(bad, max_age=1)
    assert not isinstance(ei.value, SignatureExpired)


def test_r9_tampered_timestamp(clock):
    s = TimestampSigner("k")
    t = s.sign("foo")
    v, ts, sig = t.rsplit(b".", 2)
    forged = v + b"." + kat.b64((NOW + 99999).to_bytes(4, "big")) + b"." + sig
    assert not s.validate(forged)


def test_r9_no_sep_is_plain_bad_signature():
    with pytest.raises(BadSignature) as ei:
        TimestampSigner("k").unsign(b"abc")
    assert ei.value.message == 'No "." found in value'
    assert not isinstance(ei.value, BadTimeSignature)


def test_r9_timestamp_missing():
    # validly signed by plain Signer, but no timestamp part inside
    from itsdangerous import Signer
    t = Signer("k").sign(b"foo")
    with pytest.raises(BadTimeSignature) as ei:
        TimestampSigner("k").unsign(t)
    assert ei.value.message == "timestamp missing"
    assert ei.value.payload == b"foo"


def test_r9_malformed_timestamp():
    body = b"foo.A"
    t = body + b"." + kat.signature(body, b"k", b"itsdangerous.Signer")
    with pytest.raises(BadTimeSignature) as ei:
        TimestampSigner("k").unsign(t)
    assert ei.value.message == "Malformed timestamp"
    assert ei.value.payload == b"foo"


def test_r9_out_of_range_timestamp():
    huge = (2**80).to_bytes(11, "big")
    body = b"foo." + kat.b64(huge)
    t = body + b"." + kat.signature(body, b"k", b"itsdangerous.Signer")
    with pytest.raises(BadTimeSignature) as ei:
        TimestampSigner("k").unsign(t)
    assert ei.value.message == "Malformed timestamp"


def test_r9_custom_sep_and_rotation(clock):
    s = TimestampSigner(["a", "b"], sep=":", salt="x", key_derivation="hmac")
    t = s.sign("v")
    assert t == kat.sign_ts(b"v", NOW, b"b", b"x", b":", mode="hmac")
    assert TimestampSigner(["b", "c"], sep=":", salt="x", key_derivation="hmac").unsign(t) == b"v"
    old = kat.sign_ts(b"v", NOW, b"a", b"x", b":", mode="hmac")
    assert s.unsign(old) == b"v"
