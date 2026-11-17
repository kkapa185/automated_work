import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import auth, db as dbmod, handlers as h
from .util import ApiError

# (method, path regex, handler, auth mode)
# auth: "req" = token required, "opt" = optional (invalid token -> 401), "lenient" = invalid token ignored
ROUTES = [
    ("POST", r"/users", h.register, "none"),
    ("POST", r"/users/login", h.login, "none"),
    ("GET", r"/user", h.current_user, "req"),
    ("PUT", r"/user", h.update_user, "req"),
    ("GET", r"/profiles/(?P<username>[^/]+)", h.get_profile, "opt"),
    ("POST", r"/profiles/(?P<username>[^/]+)/follow", h.follow, "req"),
    ("DELETE", r"/profiles/(?P<username>[^/]+)/follow", h.unfollow, "req"),
    ("GET", r"/articles/feed", h.feed, "req"),
    ("GET", r"/articles", h.list_articles, "opt"),
    ("POST", r"/articles", h.create_article, "req"),
    ("GET", r"/articles/(?P<slug>[^/]+)", h.read_article, "lenient"),
    ("PUT", r"/articles/(?P<slug>[^/]+)", h.update_article, "req"),
    ("DELETE", r"/articles/(?P<slug>[^/]+)", h.delete_article, "req"),
    ("GET", r"/articles/(?P<slug>[^/]+)/comments", h.list_comments, "opt"),
    ("POST", r"/articles/(?P<slug>[^/]+)/comments", h.add_comment, "req"),
    ("DELETE", r"/articles/(?P<slug>[^/]+)/comments/(?P<id>[^/]+)", h.delete_comment, "req"),
    ("POST", r"/articles/(?P<slug>[^/]+)/favorite", h.favorite, "req"),
    ("DELETE", r"/articles/(?P<slug>[^/]+)/favorite", h.unfavorite, "req"),
    ("GET", r"/tags", h.tags, "none"),
]
ROUTES = [(m, re.compile("^" + p + "$"), fn, a) for m, p, fn, a in ROUTES]


class Request:
    def __init__(self, db, headers, query, raw):
        self.db, self.headers, self.query, self.raw, self.user = db, headers, query, raw, None

    def body(self):
        try:
            return json.loads(self.raw.decode("utf-8"))
        except Exception:
            raise ApiError(422, {"body": ["is not valid JSON"]})

    def authenticate(self, mode):
        if mode == "none":
            return
        header = self.headers.get("Authorization")
        if header is None:
            if mode == "req":
                raise ApiError(401, {"token": ["is missing"]})
            return
        parts = header.split(" ", 1)
        uid = auth.verify_token(parts[1].strip()) if len(parts) == 2 and parts[0] == "Token" else None
        user = None if uid is None else self.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if user is None:
            if mode == "lenient":
                return
            raise ApiError(401, {"token": ["is invalid"]})
        self.user = user


def dispatch(db, method, target, headers, raw):
    parts = urlsplit(target)
    path = unquote(parts.path)
    if path.startswith("/api"):
        path = path[4:]
    else:
        raise ApiError(404, {"resource": ["not found"]})
    path = path.rstrip("/") or "/"
    query = {k: v[-1] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
    allowed = False
    for m, rx, fn, mode in ROUTES:
        match = rx.match(path)
        if not match:
            continue
        allowed = True
        if m != method:
            continue
        req = Request(db, headers, query, raw)
        req.authenticate(mode)
        return fn(req, **match.groupdict())
    if allowed:
        raise ApiError(405, {"method": ["not allowed"]})
    raise ApiError(404, {"resource": ["not found"]})


def make_handler(db, lock):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, status, payload):
            data = b"" if payload is None else json.dumps(payload).encode()
            self.send_response(status)
            if payload is not None:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _handle(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            raw = self.rfile.read(n) if n > 0 else b""
            if self.command == "OPTIONS":
                return self._send(204, None)
            try:
                with lock:
                    db.execute("BEGIN")
                    try:
                        status, payload = dispatch(db, self.command, self.path, self.headers, raw)
                        db.execute("COMMIT")
                    except BaseException:
                        db.execute("ROLLBACK")
                        raise
            except ApiError as e:
                status, payload = e.status, {"errors": e.errors}
            except Exception as e:  # pragma: no cover
                status, payload = 500, {"errors": {"server": ["internal error: %s" % type(e).__name__]}}
            self._send(status, payload)

        do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = _handle

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


def create_server(host="127.0.0.1", port=0):
    return Server((host, port), make_handler(dbmod.connect(), threading.Lock()))
