import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from itsdangerous import BadSignature, URLSafeTimedSerializer

s = URLSafeTimedSerializer("demo-secret", salt="demo")
token = s.dumps({"user": 1})
assert s.loads(token, max_age=60) == {"user": 1}
try:
    s.loads(token + "x")
except BadSignature as e:
    print("tamper detected:", e)
print("ok", token)
