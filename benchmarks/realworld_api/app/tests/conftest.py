import http.client
import itertools
import json
import os
import socket
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class Client:
    def __init__(self, port):
        self.port = port

    def call(self, method, path, body=None, token=None, raw=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        if token:
            h["Authorization"] = "Token " + token
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
        if data is not None:
            h["Content-Type"] = "application/json"
        c.request(method, "/api" + path, body=data, headers=h)
        r = c.getresponse()
        txt = r.read().decode()
        c.close()
        r.json = json.loads(txt) if txt else None
        r.text = txt
        return r

    get = lambda self, p, **k: self.call("GET", p, **k)
    post = lambda self, p, body=None, **k: self.call("POST", p, body, **k)
    put = lambda self, p, body=None, **k: self.call("PUT", p, body, **k)
    delete = lambda self, p, **k: self.call("DELETE", p, **k)


@pytest.fixture(scope="session")
def client():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen([os.path.join(ROOT, "serve"), "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    c = Client(port)
    for _ in range(100):
        try:
            c.get("/tags")
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("server did not start")
    yield c
    proc.terminate()
    proc.wait(timeout=10)


_n = itertools.count(1)


@pytest.fixture
def make_user(client):
    def make(prefix="u"):
        n = next(_n)
        name = "%s%d" % (prefix, n)
        r = client.post("/users", {"user": {"username": name, "email": name + "@example.com", "password": "pw-" + name}})
        assert r.status == 201, r.text
        u = r.json["user"]
        u["password"] = "pw-" + name
        return u
    return make


@pytest.fixture
def user(make_user):
    return make_user()


@pytest.fixture
def make_article(client):
    def make(u, title="Hello World", tags=None, **kw):
        a = {"title": title, "description": "desc", "body": "body text"}
        if tags is not None:
            a["tagList"] = tags
        a.update(kw)
        r = client.post("/articles", {"article": a}, token=u["token"])
        assert r.status == 201, r.text
        return r.json["article"]
    return make
