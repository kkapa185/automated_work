import hashlib

import pytest

from itsdangerous import (BadSignature, HMACAlgorithm, NoneAlgorithm, Signer,
                          SigningAlgorithm)

import kat


def test_r8_doc_example():
    s = Signer("secret-key")
    assert s.sign("my string") == b"my string.wh6tMHxLgJqB6oY1uT73iMlyrOA"
    assert s.unsign(b"my string.wh6tMHxLgJqB6oY1uT73iMlyrOA") == b"my string"
    with pytest.raises(BadSignature):
        s.unsign(b"different string.wh6tMHxLgJqB6oY1uT73iMlyrOA")


@pytest.mark.parametrize("mode", ["concat", "django-concat", "hmac", "none"])
@pytest.mark.parametrize("digest", [hashlib.sha1, hashlib.sha256, hashlib.md5])
def test_r4_r5_all_modes_known_answer(mode, digest):
    s = Signer("k3y", salt="salty", key_derivation=mode, digest_method=digest)
    expected = kat.sign(b"payload", b"k3y", b"salty", mode=mode, digest=digest)
    assert s.sign(b"payload") == expected
    assert s.derive_key() == kat.derive(b"k3y", b"salty", mode, digest)
    assert s.unsign(expected) == b"payload"


def test_r4_defaults():
    s = Signer("k")
    assert s.salt == b"itsdangerous.Signer"
    assert s.key_derivation == "django-concat"
    assert s.digest_method is hashlib.sha1
    assert s.sep == b"."
    assert s.derive_key() == hashlib.sha1(b"itsdangerous.Signer" + b"signer" + b"k").digest()


def test_r4_unknown_derivation():
    with pytest.raises(TypeError):
        Signer("k", key_derivation="bogus").derive_key()


def test_r4_none_derivation_is_key():
    assert Signer(b"raw", key_derivation="none").derive_key() == b"raw"


def test_r4_derive_explicit_key():
    s = Signer(["a", "b"])
    assert s.derive_key("a") == kat.derive(b"a", b"itsdangerous.Signer")
    assert s.derive_key() == kat.derive(b"b", b"itsdangerous.Signer")


def test_r6_signature_helpers():
    s = Signer("k")
    sig = kat.signature(b"v", b"k", b"itsdangerous.Signer")
    assert s.get_signature("v") == sig
    assert s.verify_signature(b"v", sig)
    assert s.verify_signature("v", sig.decode())
    assert not s.verify_signature(b"v", b"AAAA")
    assert not s.verify_signature(b"v", b"!")  # bad base64 -> False
    assert not s.verify_signature(b"w", sig)


def test_r6_errors_and_payload():
    s = Signer("k")
    with pytest.raises(BadSignature) as ei:
        s.unsign(b"nosep")
    assert ei.value.message == 'No "." found in value'
    assert ei.value.payload is None
    with pytest.raises(BadSignature) as ei:
        s.unsign(b"v.AAAA")
    assert ei.value.message == "Signature b'AAAA' does not match"
    assert ei.value.payload == b"v"


def test_r6_validate():
    s = Signer("k")
    assert s.validate(s.sign("x"))
    assert not s.validate(b"x.bad")
    assert not s.validate(b"x")


def test_r6_value_containing_sep():
    s = Signer("k")
    assert s.unsign(s.sign("a.b.c")) == b"a.b.c"


def test_tampering_every_position():
    s = Signer("k")
    t = bytearray(s.sign("hello"))
    for i in range(len(t)):
        m = bytearray(t)
        m[i] = ord("Z") if m[i] != ord("Z") else ord("Y")
        if m[i] == ord("."):
            continue
        assert not s.validate(bytes(m)), i


def test_wrong_key_and_salt():
    t = Signer("a").sign("x")
    assert not Signer("b").validate(t)
    assert not Signer("a", salt="other").validate(t)


def test_r3_str_and_bytes_equivalent():
    assert Signer("k", salt="s").sign("v") == Signer(b"k", salt=b"s").sign(b"v")


def test_r7_custom_sep():
    s = Signer("k", sep="!")
    t = s.sign("v")
    assert t == kat.sign(b"v", b"k", sep=b"!")
    assert s.unsign(t) == b"v"
    with pytest.raises(BadSignature) as ei:
        s.unsign(b"v.x")
    assert ei.value.message == 'No "!" found in value'


@pytest.mark.parametrize("sep", ["a", "Z", "5", "-", "_", "=", ".a"])
def test_r7_bad_sep(sep):
    with pytest.raises(ValueError):
        Signer("k", sep=sep)


@pytest.mark.parametrize("sep", [".", "!", ":", "~", b"|"])
def test_r7_ok_sep(sep):
    Signer("k", sep=sep)


def test_r16_rotation():
    old = Signer(["k1", "k2", "k3"])
    t = old.sign("v")
    assert t == kat.sign(b"v", b"k3")  # newest signs
    rotated = Signer(["k2", "k3", "k4"])
    assert rotated.unsign(t) == b"v"
    assert rotated.sign("v") == kat.sign(b"v", b"k4")
    token_k2 = kat.sign(b"v", b"k2")
    assert rotated.unsign(token_k2) == b"v"
    assert not Signer(["k3", "k4"]).validate(token_k2)  # k2 rotated out
    assert Signer(["k1", "k2"]).secret_key == b"k2"


def test_r5_none_algorithm():
    s = Signer("k", algorithm=NoneAlgorithm())
    assert s.sign("v") == b"v."
    assert s.unsign(b"v.") == b"v"
    assert not s.validate(b"v.abc")


def test_r5_algorithm_classes():
    assert NoneAlgorithm().get_signature(b"k", b"v") == b""
    a = HMACAlgorithm(hashlib.sha256)
    import hmac
    sig = hmac.new(b"k", b"v", hashlib.sha256).digest()
    assert a.get_signature(b"k", b"v") == sig
    assert a.verify_signature(b"k", b"v", sig)
    assert not a.verify_signature(b"k", b"v", sig[:-1] + b"x")
    assert HMACAlgorithm().digest_method is hashlib.sha1
    with pytest.raises(NotImplementedError):
        SigningAlgorithm().get_signature(b"", b"")


def test_r5_constant_time_compare(monkeypatch):
    import hmac
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    Signer("k").validate(Signer("k").sign("v"))
    assert calls


def test_custom_algorithm_object_used():
    s = Signer("k", algorithm=HMACAlgorithm(hashlib.sha512))
    # digest_method also feeds key derivation; algorithm alone feeds the MAC.
    import hmac
    key = kat.derive(b"k", b"itsdangerous.Signer")
    mac = kat.b64(hmac.new(key, b"v", hashlib.sha512).digest())
    assert s.sign("v") == b"v." + mac
