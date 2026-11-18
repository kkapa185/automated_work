# Requirements: JSON-file REST server (API-21)

## Product
A zero-dependency Node.js (v22, builtin `http`/`fs`/`node:test`) HTTP server launched by `./serve <db.json|db.json5> [--port N] [--host H] [--static DIR]` (repeatable; `-p/-H/-s` aliases) that exposes a JSON/JSON5 file as a REST API per `docs/README.md` (json-server v1 semantics): array collections, singular objects, filtering/sorting/pagination/embedding/`_where`/`_dependent`, atomic persistence, CORS and static files. Includes a custom JSON5 parser (no json-server or REST-from-JSON packages).

## Acceptance criteria
- R1 CLI: `./serve db.json` listens on port 3000, host 127.0.0.1 by default; `--port`, `--host`, `--static` honored (`--port=N` form too). Prints `JSON Server started on PORT :<port>` and `http://<host>:<port>`. Missing/unreadable db file -> message on stderr, exit code 1. `--help` prints usage. Port 0 permitted (prints actual port).
- R2 DB loading: `.json` parsed as JSON, `.json5` (and, as fallback, any file failing strict JSON) parsed as JSON5 (comments, unquoted keys, single quotes, trailing commas, hex, +/-Infinity/NaN, multi-line strings). Re-read from file on every start. Top-level key `$schema` is ignored (not a resource, preserved on write). Missing file -> error exit.
- R3 Resource kinds: top-level arrays = collections; top-level plain objects = singular resources; other top-level values (scalars) are not routable (404).
- R4 `GET /<coll>` returns array of all items (JSON, 2-space indent, `Content-Type: application/json; charset=utf-8`). `GET /<coll>/:id` returns the item or 404 `{"error": "Not Found"}` (pretty-printed). Unknown route/collection -> 404 same body. ids matched as strings (numeric ids in file compared by String()).
- R5 `POST /<coll>`: body JSON object; always generates a new unique random string id (body `id` ignored); returns 201 with created item (id first key); persisted. Invalid/non-object body -> 400 `{"error": ...}`. POST on singular resource/unknown -> 404 (singular: 404).
- R6 `PUT /<coll>/:id` replaces item (id kept as the existing id, body id ignored); `PATCH` shallow-merges; 200 with the item; unknown id 404. `PUT/PATCH /<singular>` replace/merge object, return it. `GET /<singular>` returns it. `DELETE` on a singular resource -> 404 (not routed). Wrong method on a known path -> 404.
- R7 `DELETE /<coll>/:id` returns 200 with the deleted item, persisted; unknown id 404. Without `_dependent`: children in other collections whose `<singular(coll)>Id` equals the id get that field set to `null`. With `_dependent=a,b`: items of those collections referencing the deleted id are deleted too (cascade). Singularization: strip trailing `s` ("posts"->"post"; "categories"->"category" via `ies`->`y`).
- R8 Conditions `field:op=value`: ops eq(default, also `field=value`) ne lt lte gt gte in contains startsWith endsWith; dotted nested paths; type-aware compare: numeric field vs numeric-parsable value compares numerically, booleans match `true`/`false`, strings compare as strings (contains/startsWith/endsWith case-insensitive); `in` splits on commas; missing field never matches except `ne`. Multiple conditions are ANDed; repeated same key allowed (ANDed). Values string-vs-number: eq `1` matches `1` and `"1"`.
- R9 `_sort=a,-b`: multi keys, `-` descending, nested paths; strings case-insensitive locale order (`localeCompare`), numbers numeric, stable; missing values last.
- R10 Pagination `_page`/`_per_page` (per_page default 10 when only `_page` given; `_per_page` alone implies page 1): envelope `{first:1, prev, next, last, pages, items, data}` with null prev/next at ends; invalid values (non-numeric, <1) normalized (page->1, per_page->10); page beyond last clamps to last page; empty collection: pages=1 (pages = max(1,ceil(items/per_page)), last=pages). Applied after filter and sort; items = filtered count.
- R11 `_embed=a,b` (repeatable): on collection `X`, `a` is a child collection with `<singular(X)>Id` -> embeds array under key `a`; or `a` is a parent (singular name, `post` -> collection `posts` via item's `postId`) embeds the parent object (null if none). Works on `GET /<coll>`, `/<coll>/:id`, with filters/pagination. Unknown embed ignored. Stored data not modified.
- R12 `_where` JSON: `{"field":{"op":val}}`, `{"and":[..]}`, `{"or":[..]}`, `{"not":{..}}`, nested objects for nested paths (`{"author":{"name":{"lt":"m"}}}`), shorthand `{"field":value}` = eq. When valid it overrides (ignores) normal condition params; invalid JSON -> ignored (normal params apply). Sorting/pagination still apply.
- R13 Persistence: every mutation written to the db file atomically (temp file in same dir + rename), pretty-printed 2-space JSON (a `.json5` source is written as JSON text, which is valid JSON5); writes serialized; survives restart.
- R14 CORS: `Access-Control-Allow-Origin: *` on all responses, `OPTIONS` preflight -> 204 with Allow-Methods (GET,HEAD,PUT,POST,PATCH,DELETE,OPTIONS) and Allow-Headers echoing requested headers (default `*`... echo `Access-Control-Request-Headers`).
- R15 Static: `--static` dirs (repeatable) and `./public` when it exists serve files with MIME types (`/` -> index.html); path traversal blocked; API routes take precedence over static only when they match a resource; HEAD works. Non-matching -> 404 JSON.
- R16 Robustness: malformed JSON body -> 400; body limit generous; unknown-ids 404; `HEAD` supported on GETs; concurrent requests safe (single-threaded in-memory + serialized writes). Ids generated are unique vs. existing.
- R17 Performance: 10k-item collection GET with filter+sort+page < 1s; 200 sequential POSTs complete quickly (persist coalesced but each response after write durable).
- R18 Deliverables: `serve` executable, `package.json` (`npm test`), `test/` API suite covering every README example (all routes, each operator, sort, pagination envelope, embed both directions, `_where` example, `_dependent`, null-FK on delete, static, JSON5 db, persistence across restart, CORS), README.md at root.

## Assumptions
- README `GET /posts?views:gt=100` etc. are the exact examples; test fixture is the README db (posts/comments/profile).
- Beyond README, json-server v1 behaviour used for details (200 on DELETE returning deleted item; PUT keeps id).
- `-s` repeatable static dirs; `./public` auto-added only if it exists.
- Empty-collection pagination: items 0, pages 1, first 1, last 1, prev/next null, data [].
- Item with numeric ids in file stay numeric on disk; routes compare as strings.

## Test strategy
`node:test` + real HTTP against spawned `./serve` on port 0/random with temp copy of db: R4-R12 integration tests by example with hand-computed expectations; R2 unit tests of JSON5 parser; R13 restart test; R14/R15 HTTP; R17 benchmark test; R1 CLI tests (exit codes, banner).

## Milestones
Not needed (small product).
