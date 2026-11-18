# JSON REST Server

Zero-code REST API server backed by a JSON (or JSON5) file, compatible with the json-server v1 documentation
in `docs/README.md` (normative). Zero dependencies; Node.js >= 20 (tested on 22). Written from the spec.

## Install / run / test
```bash
# no install step needed (no dependencies)
./serve db.json [--port 3000] [--host 127.0.0.1] [--static ./public]   # -p, -H, -s; -s is repeatable
npm test        # node --test test/*.test.js
```
Prints `JSON Server started on PORT :3000` and the URL. `./public` is served automatically if it exists
(plus any `--static` dirs). A sample `db.json` is included.

## Features
- Arrays → collections (`GET/POST /posts`, `GET/PUT/PATCH/DELETE /posts/:id`); objects → singular
  resources (`GET/PUT/PATCH /profile`). Ids are strings; POST without id generates a random one (201).
- Filtering `field:op=value` (`eq ne lt lte gt gte in contains startsWith endsWith`, dotted paths, type-aware),
  `_sort=a,-b`, `_page`/`_per_page` envelope, `_embed` (children via `<singular>Id`, parents), `_where` JSON
  (`and`/`or`/`not`), `DELETE ...?_dependent=comments`.
- 404 `{"error": "NotFound"}`, CORS `*`, pretty-printed JSON, static files.
- Mutations are written atomically (temp file + rename, serialized) as JSON and survive restarts.

## Design
`src/json5.js` (own JSON5 parser) · `src/db.js` (load + atomic serialized saves) · `src/query.js`
(filter/sort/paginate/embed) · `src/app.js` (HTTP routing, CORS, static) · `src/cli.js` (arguments).
Pipeline for list requests: filter (`_where` overrides conditions when valid) → sort → paginate → embed.

## Assumptions (where the spec is silent)
- POST with an existing id → 400; non-object / invalid JSON body → 400 `{"error": ...}`; POST on a singular resource → 404.
- Missing field matches only `ne`; unknown operators are ignored; repeated conditions are ANDed.
- Pagination: `_per_page` default 10; invalid values normalized (page<1 → 1, per_page<1 → 10, page>pages → last);
  an empty result has `pages: 1, last: 1`.
- Sorting: numbers numerically, strings by code point; missing values last.
- Embedding of a parent uses `<name>Id` and a plural collection (`post` → `posts`); absent parent → `null`.
- A `.json5` database file is rewritten as plain JSON (valid JSON5). A top-level `$schema` key is preserved.
- API resources take precedence over static files of the same name.
