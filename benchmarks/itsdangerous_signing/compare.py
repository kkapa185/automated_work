"""Token-level interoperability between the reference itsdangerous and the generated package."""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run_python_driver  # noqa: E402

DRIVER = r'''
import json, sys, time, hashlib, datetime
cfg = json.loads(sys.stdin.read())
time.time = lambda: cfg["now"]
import itsdangerous as its
from itsdangerous import (Signer, TimestampSigner, Serializer, TimedSerializer, URLSafeSerializer,
                          URLSafeTimedSerializer, BadSignature, BadTimeSignature, SignatureExpired, BadPayload, BadData)
def s(x): return x.decode() if isinstance(x, bytes) else x
out = {"tokens": {}, "verify": {}, "errors": {}}
T = out["tokens"]
T["signer"] = s(Signer("secret").sign("hello"))
T["signer_salt_sep"] = s(Signer(b"k", salt="custom", sep="|").sign(b"v"))
for kd in ("concat", "django-concat", "hmac", "none"):
    T["kd_" + kd] = s(Signer("secret", key_derivation=kd).sign("x"))
T["sha256"] = s(Signer("secret", digest_method=hashlib.sha256).sign("abc"))
T["rotation"] = s(Signer(["old", "new"]).sign("rot"))
T["timestamp"] = s(TimestampSigner("secret").sign("hello"))
T["ser"] = s(Serializer("secret").dumps({"id": 5, "name": "itsdangerous", "list": [1, 2.5, None, True]}))
T["timed_ser"] = s(TimedSerializer("secret").dumps([1, 2, 3]))
T["url"] = s(URLSafeSerializer("secret").dumps({"a": "b" * 5}))
T["url_compressed"] = s(URLSafeSerializer("secret").dumps({"a": "b" * 200}))
T["url_timed"] = s(URLSafeTimedSerializer("secret", salt="activate").dumps({"user": 42}))
# verify tokens produced by the OTHER implementation
V = out["verify"]
for name, tok in cfg.get("foreign", {}).items():
    try:
        if name.startswith("kd_"):
            V[name] = s(Signer("secret", key_derivation=name[3:]).unsign(tok))
        elif name == "signer": V[name] = s(Signer("secret").unsign(tok))
        elif name == "signer_salt_sep": V[name] = s(Signer(b"k", salt="custom", sep="|").unsign(tok))
        elif name == "sha256": V[name] = s(Signer("secret", digest_method=hashlib.sha256).unsign(tok))
        elif name == "rotation": V[name] = s(Signer(["new"]).unsign(tok))
        elif name == "timestamp":
            v, ts = TimestampSigner("secret").unsign(tok, max_age=60, return_timestamp=True)
            V[name] = [s(v), ts.isoformat()]
        elif name == "ser": V[name] = Serializer("secret").loads(tok)
        elif name == "timed_ser": V[name] = TimedSerializer("secret").loads(tok, max_age=60)
        elif name in ("url", "url_compressed"): V[name] = URLSafeSerializer("secret").loads(tok)
        elif name == "url_timed": V[name] = URLSafeTimedSerializer("secret", salt="activate").loads(tok, max_age=60)
    except Exception as e:
        V[name] = "ERR:" + type(e).__name__
E = out["errors"]
def err(fn):
    try:
        fn(); return "no error"
    except Exception as e:
        return [type(e).__name__, str(e), [c.__name__ for c in type(e).__mro__ if c.__name__ in ("BadData","BadSignature","BadTimeSignature","SignatureExpired","BadPayload","BadHeader")]]
E["tampered"] = err(lambda: Signer("secret").unsign("jello" + T["signer"][5:]))
E["no_sep"] = err(lambda: Signer("secret").unsign("nosep"))
E["wrong_key"] = err(lambda: Signer("other").unsign(T["signer"]))
E["expired"] = err(lambda: (setattr(time, "time", lambda: cfg["now"] + 100), TimestampSigner("secret").unsign(T["timestamp"], max_age=10))[1])
time.time = lambda: cfg["now"]
E["bad_sep"] = err(lambda: Signer("secret", sep="a"))
E["validate"] = [Signer("secret").validate(T["signer"]), Signer("secret").validate("x.y")]
E["b64"] = [s(its.base64_encode(b"\xff\xfe\x00")), its.base64_decode("_-4A") == b"\xff\xfe\x00"]
E["b64_bad"] = err(lambda: its.base64_decode("a"))
E["unsafe"] = list(URLSafeSerializer("secret").loads_unsafe(T["url"][:-2] + "zz"))
print(json.dumps(out, default=str))
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    refpath, apppath = Path(a.reference) / "src", Path(a.app)
    if (apppath / "src" / "itsdangerous").exists():
        apppath = apppath / "src"
    base = {"now": 1_700_000_000}
    ref = run_python_driver(DRIVER, refpath, a.reference, base)
    got = run_python_driver(DRIVER, apppath, a.app, base)
    checks = [check("driver runs against generated package", "__error__" not in got, got.get("__error__", ""))]
    if "__error__" in got:
        return finish(a.out, checks)
    for k, v in ref["tokens"].items():
        checks.append(check(f"token identical: {k}", got["tokens"].get(k) == v, f"{got['tokens'].get(k)} vs {v}"))
    ref_verifies_app = run_python_driver(DRIVER, refpath, a.reference, base | {"foreign": got["tokens"]})
    app_verifies_ref = run_python_driver(DRIVER, apppath, a.app, base | {"foreign": ref["tokens"]})
    expected = run_python_driver(DRIVER, refpath, a.reference, base | {"foreign": ref["tokens"]})["verify"]
    for k, v in expected.items():
        checks.append(check(f"generated verifies reference token: {k}", app_verifies_ref.get("verify", {}).get(k) == v,
                            f"{app_verifies_ref.get('verify', {}).get(k)} vs {v}"))
        checks.append(check(f"reference verifies generated token: {k}", ref_verifies_app.get("verify", {}).get(k) == v,
                            f"{ref_verifies_app.get('verify', {}).get(k)} vs {v}"))
    for k, v in ref["errors"].items():
        g = got["errors"].get(k)
        ok = g == v if k in ("validate", "b64", "unsafe") else (isinstance(g, list) and g[0] == v[0] and g[2] == v[2])
        checks.append(check(f"error behaviour: {k}", ok, f"{g} vs {v}"))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
