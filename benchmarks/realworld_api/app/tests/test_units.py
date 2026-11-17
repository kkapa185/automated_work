"""Unit tests: slug, JWT, timestamps, password hashing (R11, R20, R21, R6)."""
import re

from conduit import auth
from conduit.util import now_iso, slugify


def test_slugify_r11():
    assert slugify("Hello, World!  2024") == "hello-world-2024"
    assert slugify("  --Already-slug-- ") == "already-slug"
    assert slugify("???") == "article"


def test_timestamp_format_r20():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", now_iso())


def test_jwt_roundtrip_and_tamper_r6():
    s = b"k" * 32
    t = auth.make_token(7, "bob", secret=s, now=1000, ttl=100)
    assert auth.verify_token(t, secret=s, now=1050) == 7
    assert auth.verify_token(t, secret=s, now=1100) is None  # expired
    assert auth.verify_token(t, secret=b"x" * 32, now=1050) is None
    h, b, sg = t.split(".")
    assert auth.verify_token(h + "." + b + "x." + sg, secret=s, now=1050) is None
    assert auth.verify_token("garbage", secret=s) is None


def test_password_hash_r21():
    h = auth.hash_password("secret")
    assert "secret" not in h
    assert auth.check_password("secret", h)
    assert not auth.check_password("Secret", h)
    assert auth.hash_password("secret") != h  # salted
