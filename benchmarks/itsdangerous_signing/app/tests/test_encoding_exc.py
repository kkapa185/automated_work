import pytest

from itsdangerous import (BadData, BadHeader, BadPayload, BadSignature,
                          BadTimeSignature, SignatureExpired, base64_decode,
                          base64_encode, want_bytes)


def test_r1_want_bytes():
    assert want_bytes("é") == b"\xc3\xa9"
    assert want_bytes(b"x") == b"x"
    assert want_bytes("é", "latin-1") == b"\xe9"


def test_r2_base64_encode_no_padding_urlsafe():
    assert base64_encode(b"a") == b"YQ"
    assert base64_encode("ab") == b"YWI"
    assert base64_encode(b"abc") == b"YWJj"
    assert base64_encode(b"\xfb\xff\xfe") == b"-__-"
    assert base64_encode(b"") == b""


def test_r2_base64_decode():
    assert base64_decode("YQ") == b"a"
    assert base64_decode(b"YWI") == b"ab"
    assert base64_decode(b"-__-") == b"\xfb\xff\xfe"
    assert base64_decode("YQ==") == b"a"


@pytest.mark.parametrize("bad", ["Y", "YWJjZ", b"A"])
def test_r2_base64_decode_invalid(bad):
    with pytest.raises(BadData) as ei:
        base64_decode(bad)
    assert ei.value.message == "Invalid base64-encoded data"


def test_r15_hierarchy_and_attrs():
    assert issubclass(BadSignature, BadData)
    assert issubclass(BadTimeSignature, BadSignature)
    assert issubclass(SignatureExpired, BadTimeSignature)
    assert issubclass(BadHeader, BadSignature)
    assert issubclass(BadPayload, BadData)
    assert not issubclass(BadPayload, BadSignature)
    e = BadData("m")
    assert str(e) == "m" and e.message == "m"
    e = BadSignature("m", b"p")
    assert e.payload == b"p" and BadSignature("m").payload is None
    e = BadTimeSignature("m", b"p", "d")
    assert (e.message, e.payload, e.date_signed) == ("m", b"p", "d")
    e = BadHeader("m", b"p", {"a": 1}, ValueError())
    assert e.header == {"a": 1} and isinstance(e.original_error, ValueError)
    assert e.payload == b"p"
    err = ValueError()
    e = BadPayload("m", err)
    assert e.original_error is err and e.message == "m"
