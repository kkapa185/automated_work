import base64
import hashlib
import hmac
import json
import os
import time

SECRET = os.urandom(32)
TOKEN_TTL = 30 * 24 * 3600


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(msg, secret):
    return _b64(hmac.new(secret, msg.encode(), hashlib.sha256).digest())


def make_token(user_id, username, secret=SECRET, now=None, ttl=TOKEN_TTL):
    now = int(time.time() if now is None else now)
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps({"id": user_id, "username": username, "iat": now, "exp": now + ttl},
                           separators=(",", ":")).encode())
    msg = head + "." + body
    return msg + "." + _sign(msg, secret)


def verify_token(token, secret=SECRET, now=None):
    """Return the user id for a valid token, else None."""
    try:
        head, body, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(head + "." + body, secret)):
            return None
        if json.loads(_unb64(head)).get("alg") != "HS256":
            return None
        claims = json.loads(_unb64(body))
        if claims["exp"] <= (time.time() if now is None else now):
            return None
        uid = claims["id"]
        return uid if isinstance(uid, int) else None
    except Exception:
        return None


def hash_password(password):
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return "scrypt$%s$%s" % (salt.hex(), h.hex())


def check_password(password, stored):
    try:
        _, salt, h = stored.split("$")
        c = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(c, bytes.fromhex(h))
    except Exception:
        return False
