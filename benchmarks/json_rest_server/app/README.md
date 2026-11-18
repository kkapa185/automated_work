# JSON REST Server

Zero-code REST API server: point it at a JSON (or JSON5) file and get a full REST API for
front-end prototyping (json-server v1 compatible semantics, per `docs/README.md`).
Pure Node.js (≥ 20, built-in modules only) — no dependencies to install.

## Run

```bash
./serve <db.json|db.json5> [--port <port>] [--host 127.0.0.1] [--static <dir>]
./serve examples/db.json --port 3000
curl http://127.0.0.1:3000/posts/1
```

Defaults: port `3000`, host `127.0.0.1`. `--static`/`-s` is repeatable; `./public` is served too if it
exists. Short flags `-p`, `-H`, `-s`; `--port=N` also works. On start it prints
`JSON Server started on PORT :<port>` and the URL. A missing/invalid db file exits with status 1.

## API summary

* Top-level arrays → collections: `GET/POST /posts`, `GET/PUT/PATCH/DELETE /posts/:id`.
  Top-level objects → singular resources: `GET/PUT/PATCH /profile`.
* `POST` always generates a new random string id (a body `id` is ignored) and answers `201`.
  `PUT` replaces, `PATCH` shallow-merges; the id never changes. `DELETE` returns the removed item.
* Unknown routes/ids: `404 {"error": "Not Found"}`. Malformed bodies: `400 {"error": ...}`.
* Conditions `field:op=value` — `eq ne lt lte gt gte in contains startsWith endsWith`, dotted paths,
  type-aware (numbers compare numerically, `true`/`false` match booleans; the string operators are
  case-insensitive). Multiple conditions are ANDed.
* `_sort=a,-b` — multi-key, strings compared case-insensitively in locale order, missing values last.
* `_page`/`_per_page` (default 10) → `{first, prev, next, last, pages, items, data}`.
* `_embed=comments` (children through `<singular>Id`) and `_embed=post` (parent through `postId`).
* `_where={"or":[{"views":{"gt":100}},{"author":{"name":{"lt":"m"}}}]}` with `and`/`or`/`not`;
  when valid it replaces the ordinary condition params (sort/pagination/embed still apply).
* `DELETE /posts/1?_dependent=comments` cascades; without it children keep existing but their
  `postId` becomes `null`.
* CORS: `Access-Control-Allow-Origin: *`, `OPTIONS` preflight → 204.

Mutations are written to the db file atomically (temp file + rename, 2-space indent) and survive
restarts. The file is re-read on start. A `.json5` db is read as JSON5 and written back as JSON
(valid JSON5). `$schema` keys are ignored and preserved.

## Test

```bash
npm test      # node:test; spawns ./serve on ephemeral ports against temp copies of fixtures
```

Suites: `test/api.test.js` (every documented example and route, operators, sort, pagination, embed,
`_where`, `_dependent`, persistence/restart, JSON5 db, CORS, static), `test/json5.test.js`,
`test/cli.test.js`, `test/perf.test.js` (10k-item query < 1 s). Test names carry the requirement IDs
from `.orchestrator/requirements.md`.

## Design

`src/json5.js` parser · `src/store.js` in-memory db + coalesced atomic persistence ·
`src/query.js` filters/sort/pagination/embed · `src/server.js` routing, CORS, static · `src/cli.js`.
Requests run on a single thread against the in-memory store; every mutation awaits the file write
before responding.

## Assumptions

* `DELETE` answers 200 with the deleted item; `PUT` keeps the existing id.
* `lt/gt` on strings use plain (case-sensitive) code-unit order; `eq` is exact for strings.
* Embedding a parent whose id is missing gives `null`; unknown `_embed` names are ignored.
* Pagination of an empty result: `pages: 1`, `items: 0`, `data: []`. Out-of-range `_page` clamps to
  the last page; invalid `_page`/`_per_page` fall back to 1 / 10.
* Singularisation for foreign keys: `ies→y`, trailing `s` removed.
