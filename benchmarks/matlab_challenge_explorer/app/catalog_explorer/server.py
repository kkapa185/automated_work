"""HTTP API + UI (stdlib ThreadingHTTPServer)."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, unquote, urlsplit

# filter param -> (record field, kind)
FILTERS = {
    "difficulty": ("difficulty", "scalar"),
    "technology_trend": ("technology_trends", "list"),
    "product": ("mathworks_products", "list"),
    "platform": ("mathworks_platforms", "list"),
    "project_type": ("project_type", "list"),
    "application_area": ("application_areas", "list"),
    "hardware_required": ("hardware_required", "scalar"),
    "partner": ("partners", "list"),
    "has_partner": ("has_partner", "bool"),
}


class BadRequest(ValueError):
    pass


def _values(field_kind: str, rec: dict, field: str) -> list[str]:
    v = rec.get(field)
    if field_kind == "bool":
        return ["true" if v else "false"]
    if field_kind == "list":
        return [str(x) for x in (v or [])]
    return [str(v)] if v not in (None, "") else []


def _split_values(raw: list[str]) -> list[str]:
    return [v.strip().lower() for v in raw if v.strip()]


def parse_filters(query: dict[str, list[str]]) -> dict:
    """Validate and normalise query parameters into a filter spec."""
    spec: dict = {"q": [w for v in query.get("q", []) for w in v.lower().split()]}
    for param, (_, kind) in FILTERS.items():
        vals = _split_values(query.get(param, []))
        if kind == "bool":
            for v in vals:
                if v not in ("true", "false"):
                    raise BadRequest(f"{param} must be 'true' or 'false'")
        if vals:
            spec[param] = vals
    return spec


def _haystack(rec: dict) -> str:
    return " \n".join([rec["title"], rec["summary"], *rec["expertise_gained_original"], *rec["mathworks_products"]]).lower()


def matches(rec: dict, spec: dict, skip: str | None = None) -> bool:
    hay = None
    for w in spec.get("q", []) if skip != "q" else []:
        hay = hay or _haystack(rec)
        if w not in hay:
            return False
    for param, (field, kind) in FILTERS.items():
        if param == skip or param not in spec:
            continue
        have = {x.lower() for x in _values(kind, rec, field)}
        if not have.intersection(spec[param]):
            return False
    return True


def filter_projects(projects: list[dict], spec: dict) -> list[dict]:
    return [p for p in projects if matches(p, spec)]


def compute_facets(projects: list[dict], spec: dict | None = None) -> dict[str, list[dict]]:
    """Value -> number of projects, per filterable field.

    With no ``spec`` the counts cover the whole catalog.  With a filter ``spec`` each field is
    counted over the projects matching every filter *except that field's own* (disjunctive
    faceting), so checking a value never zeroes out its siblings.
    """
    spec = spec or {}
    facets: dict[str, list[dict]] = {}
    for param, (field, kind) in FILTERS.items():
        counts: dict[str, int] = {}
        for p in (q for q in projects if matches(q, spec, skip=param)):
            for v in set(_values(kind, p, field)):
                counts[v] = counts.get(v, 0) + 1
        if kind == "bool":
            counts.setdefault("true", 0)
            counts.setdefault("false", 0)
        facets[param] = [{"value": v, "count": c} for v, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
    return facets


def make_handler(projects: list[dict], index_html: bytes):
    by_id = {p["id"]: p for p in projects}

    class Handler(BaseHTTPRequestHandler):
        server_version = "ChallengeExplorer/1.0"

        def log_message(self, *a):  # keep the console quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, obj):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, status: int, msg: str):
            self._json(status, {"error": msg})

        def do_GET(self):  # noqa: N802
            url = urlsplit(self.path)
            path = url.path.rstrip("/") or "/"
            query = parse_qs(url.query, keep_blank_values=False)
            try:
                if path == "/":
                    return self._send(200, index_html, "text/html; charset=utf-8")
                if path == "/api/projects":
                    res = filter_projects(projects, parse_filters(query))
                    return self._json(200, {"count": len(res), "projects": res})
                if path.startswith("/api/projects/"):
                    pid = unquote(path[len("/api/projects/"):])
                    if pid in by_id:
                        return self._json(200, by_id[pid])
                    return self._error(404, f"project not found: {pid}")
                if path == "/api/facets":
                    spec = parse_filters(query)
                    return self._json(200, compute_facets(projects, spec))
                return self._error(404, "not found")
            except BadRequest as e:
                return self._error(400, str(e))

        do_HEAD = do_GET  # noqa: N815

        def _not_allowed(self):
            self._error(405, "method not allowed")

        do_POST = do_PUT = do_DELETE = do_PATCH = _not_allowed  # noqa: N815

    return Handler


def load_index() -> bytes:
    return resources.files("catalog_explorer").joinpath("static/index.html").read_bytes()


def make_server(projects: list[dict], host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(projects, load_index()))
    httpd.daemon_threads = True
    return httpd
