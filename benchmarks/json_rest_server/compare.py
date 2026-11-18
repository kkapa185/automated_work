"""Same db.json and request sequence against reference json-server and the generated ./serve."""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish  # noqa: E402

DB = {
    "posts": [
        {"id": "1", "title": "Hello World", "views": 100, "published": True, "author": {"name": "typicode"}, "tags": ["a", "b"]},
        {"id": "2", "title": "another title", "views": 200, "published": False, "author": {"name": "ann"}, "tags": ["b"]},
        {"id": "3", "title": "Third Post", "views": 50, "published": True, "author": {"name": "typicode"}, "tags": []},
        {"id": "4", "title": "fourth", "views": 200, "published": True, "author": {"name": "zed"}, "tags": ["c"]},
    ],
    "comments": [
        {"id": "1", "text": "c1", "postId": "1"}, {"id": "2", "text": "c2", "postId": "1"},
        {"id": "3", "text": "c3", "postId": "2"}, {"id": "4", "text": "c4", "postId": "4"},
    ],
    "profile": {"name": "typicode", "age": 7},
}

REQUESTS = [
    ("GET", "/posts"), ("GET", "/posts/2"), ("GET", "/posts/99"), ("GET", "/nothing"), ("GET", "/profile"),
    ("GET", "/posts?views:gt=90"), ("GET", "/posts?views:gte=200"), ("GET", "/posts?views:lt=100"), ("GET", "/posts?views:ne=200"),
    ("GET", "/posts?views=200"), ("GET", "/posts?title:contains=TITLE"), ("GET", "/posts?title:startsWith=an"),
    ("GET", "/posts?title:endsWith=POST"), ("GET", "/posts?author.name:eq=typicode"), ("GET", "/posts?published=true"),
    ("GET", "/posts?views:gt=60&published=true"), ("GET", "/posts?_sort=views"), ("GET", "/posts?_sort=-views,title"),
    ("GET", "/posts?_page=1&_per_page=2"), ("GET", "/posts?_page=2&_per_page=3"), ("GET", "/posts?_page=9&_per_page=2"),
    ("GET", "/posts?_sort=-views&_page=1&_per_page=3"), ("GET", "/posts/1?_embed=comments"), ("GET", "/posts?_embed=comments"),
    ("GET", "/comments?_embed=post"), ("GET", "/comments/3?_embed=post"),
    ("GET", '/posts?_where={"or":[{"views":{"lt":60}},{"id":{"eq":"2"}}]}'),
    ("POST", "/posts", {"title": "created", "views": 1}), ("POST", "/posts", {"id": "fixed", "title": "with id"}),
    ("GET", "/posts?_sort=title"), ("PUT", "/posts/2", {"title": "replaced", "views": 5}), ("GET", "/posts/2"),
    ("PATCH", "/posts/3", {"views": 51, "extra": {"k": 1}}), ("GET", "/posts/3"), ("PATCH", "/posts/404", {"x": 1}),
    ("PUT", "/profile", {"name": "new"}), ("PATCH", "/profile", {"age": 8}), ("GET", "/profile"),
    ("DELETE", "/posts/1?_dependent=comments"), ("GET", "/comments"), ("DELETE", "/posts/4"), ("GET", "/comments"),
    ("DELETE", "/posts/404"), ("POST", "/comments", {"text": "new c", "postId": "2"}), ("GET", "/posts/2?_embed=comments"),
    ("GET", "/posts"),
]


def mask(v, known):
    """Replace server-generated ids (not present in the original data or request bodies) with a placeholder."""
    if isinstance(v, dict):
        return {k: ("<generated>" if k == "id" and isinstance(x, str) and x not in known else mask(x, known)) for k, x in v.items()}
    if isinstance(v, list):
        return [mask(x, known) for x in v]
    return v


def req(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            raw, code, hdr = resp.read(), resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw, code, hdr = e.read(), e.code, dict(e.headers)
    try:
        val = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        val = raw.decode(errors="replace")[:200]
    return code, val, hdr


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(argv, cwd, port):
    p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/profile", timeout=2)
            return p
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    return p


def stop(p):
    try:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=10)
    except Exception:  # noqa: BLE001
        pass


def session(kind, app, ref):
    d = tempfile.mkdtemp()
    db = Path(d) / "db.json"
    db.write_text(json.dumps(DB, indent=2))
    port = free_port()
    argv = (["node", str(ref / "lib" / "bin.js"), str(db), "--port", str(port)] if kind == "ref"
            else [str(app / "serve"), str(db), "--port", str(port)])
    try:
        p = start(argv, d if kind == "ref" else str(app), port)
    except OSError as exc:
        return {"error": repr(exc)}
    base = f"http://127.0.0.1:{port}"
    known = {"1", "2", "3", "4", "fixed"}
    out = []
    for r in REQUESTS:
        try:
            code, val, hdr = req(base, *r)
            out.append((code, mask(val, known), hdr.get("Access-Control-Allow-Origin")))
            if r[0] != "GET":
                time.sleep(0.15)  # the reference persists asynchronously; let writes settle
        except Exception as exc:  # noqa: BLE001
            out.append(("EXC", repr(exc)[:100], None))
    time.sleep(1.5)
    stop(p)
    try:
        persisted = mask(json.loads(db.read_text()), known)
    except Exception as exc:  # noqa: BLE001
        persisted = f"unreadable: {exc!r}"
    p = start(argv, d if kind == "ref" else str(app), port)
    try:
        after = mask(req(base, "GET", "/posts")[1], known)
    except Exception as exc:  # noqa: BLE001
        after = repr(exc)
    stop(p)
    return {"responses": out, "persisted": persisted, "after_restart": after}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app).resolve(), Path(a.reference)
    r, g = session("ref", app, ref), session("app", app, ref)
    checks = []
    if "error" in g:
        checks.append(check("server starts", False, g["error"]))
        return finish(a.out, checks)
    for i, (rq, rr, gg) in enumerate(zip(REQUESTS, r["responses"], g["responses"])):
        label = f"{rq[0]} {rq[1]}"[:80]
        checks.append(check(f"{i:02d} {label}: status and body identical", rr[:2] == gg[:2], f"got {gg[0]} {json.dumps(gg[1])[:250]}\nexpected {rr[0]} {json.dumps(rr[1])[:250]}"))
    checks.append(check("CORS header present on responses", all(x[2] == "*" for x in g["responses"] if x[0] != "EXC")))
    checks.append(check("database file content after mutations identical", r["persisted"] == g["persisted"], json.dumps(g["persisted"])[:300]))
    checks.append(check("state survives restart", r["after_restart"] == g["after_restart"]))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
