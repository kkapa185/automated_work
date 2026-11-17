"""Smoke demo: sign, tamper-check and expire tokens."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itsdangerous import (BadSignature, Signer, URLSafeTimedSerializer)  # noqa: E402

signer = Signer("secret-key")
token = signer.sign("my string")
assert token == b"my string.wh6tMHxLgJqB6oY1uT73iMlyrOA", token
assert signer.unsign(token) == b"my string"
print(token.decode())

s = URLSafeTimedSerializer("secret-key", salt="activate")
t = s.dumps({"id": 42})
assert s.loads(t, max_age=60) == {"id": 42}
try:
    s.loads(t + "x")
except BadSignature as e:
    print("tamper detected:", e)
else:
    raise SystemExit("tampering not detected")
print(t)
