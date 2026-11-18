# API-21: Zero-code REST API server backed by a JSON file (`json-server` v1 compatible)

Build a server that turns a JSON (or JSON5) database file into a full REST API, for front-end
prototyping. Runtime contract: `./serve <db.json> [--port <port>] [--host 127.0.0.1] [--static <dir>]`
(any language/framework; do not use json-server itself or similar "REST from JSON" packages). The
project's README is provided in `docs/README.md` and is **normative** for routes, query parameters,
response shapes and status codes.

* Top-level arrays become collections (`GET/POST /posts`, `GET/PUT/PATCH/DELETE /posts/:id`), top-level
  objects become singular resources (`GET/PUT/PATCH /profile`). Ids are strings; `POST` without an id
  generates a unique random id. Responses are JSON (pretty-printed with 2-space indentation), 201 for
  creation, 404 `{"error": "NotFound"}` for unknown routes/ids; CORS headers as in the README.
* Query parameters exactly as documented: conditions `field:op=value` (`eq ne lt lte gt gte in contains
  startsWith endsWith`, nested fields with dots, type-aware comparison), `_sort=a,-b`,
  `_page`/`_per_page` (paginated envelope `{first, prev, next, last, pages, items, data}`), `_embed`
  (children via `<singular>Id` foreign keys and parents), `_where` JSON queries (`and`/`or`/`not`),
  `_dependent` for cascading deletes.
* Mutations are persisted to the database file (written atomically) and survive restarts; the file is
  re-read on start. `--static` serves files (default `./public` if it exists).

Deliverables: the server, an API test-suite covering every documented example, and a README.
