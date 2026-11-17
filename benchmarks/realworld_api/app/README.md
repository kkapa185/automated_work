# Conduit API

Backend for "Conduit", a Medium-style blogging platform, implementing the RealWorld API described in
`spec/openapi.yml`. Pure Python 3 standard library at runtime (threaded `http.server`, `sqlite3`,
scrypt password hashing, hand-rolled HS256 JWT) — nothing to install to run it.

## Run
    ./serve --port 8000        # serves http://127.0.0.1:8000/api

Each start creates a fresh in-memory SQLite database (schema created on boot, no external services).
Auth: `Authorization: Token <jwt>` (tokens valid 30 days, secret random per process start).

## Test
    python3 -m pip install -r requirements-dev.txt   # pytest only
    python3 -m pytest -q tests

Integration tests launch the real `./serve` on a free port and exercise every endpoint and error case over
HTTP (test docstrings reference requirement ids R1–R25 in `.orchestrator/requirements.md`); `tests/test_units.py`
covers slug, JWT, timestamp and password helpers.

## Design
- `conduit/server.py` – routing table, auth modes (required / optional / lenient), JSON I/O, error mapping, CORS.
  Each request runs in one transaction under a global lock (rollback on any error).
- `conduit/handlers.py` – endpoint logic and serializers (`favorited`, `favoritesCount`, `following` computed per caller).
- `conduit/db.py` – schema; `conduit/auth.py` – scrypt + JWT; `conduit/util.py` – slugs, timestamps, errors.
- Errors: `{"errors": {field: [messages]}}` with 401/403/404/405/409/422. Check order: 401, 404, 403, 422.

## Assumptions
- Usernames are exact-match; emails are unique case-insensitively. Login failure is 401.
- Slug collisions get `-2`, `-3`… suffixes; duplicate titles are allowed. Title update regenerates the slug.
- `PUT /user` and `PUT /articles/:slug` with no updatable fields return 422.
- Duplicate tags in a `tagList` are dropped (first occurrence kept). Following yourself is allowed.
- `GET /articles/:slug` ignores an invalid token (spec lists no 401); other optional-auth endpoints return 401 for an invalid token.
