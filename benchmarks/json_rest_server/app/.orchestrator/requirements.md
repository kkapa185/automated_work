# Requirements — REST API server from a JSON/JSON5 file (json-server v1 compatible)

## Product
A zero-dependency Node.js (v22, built-in `http`, `fs`, `node:test`) HTTP server launched by `./serve <db.json|db.json5> [--port N] [--host H] [--static DIR]`.
It loads a database file, exposes top-level arrays as collections and top-level objects as singular resources, supports
filtering/sorting/pagination/embedding/`_where`/`_dependent`, persists mutations atomically to the file, serves static files and CORS.
Spec of record: `docs/README.md` (normative) + ticket. Own JSON5 parser (no third-party packages).

## Acceptance criteria
### CLI / startup
- R1 `./serve db.json` starts on port 3000, host 127.0.0.1 by default; prints `JSON Server started on PORT :<port>` and `http://<host>:<port>`-style line (README example uses localhost). `--port`/`-p`, `--host`/`-H`, `--static`/`-s` (repeatable) supported; `--help` prints usage. Missing/unreadable db file → error message, non-zero exit.
- R2 DB file may be JSON or JSON5 (comments, unquoted keys, single quotes, trailing commas, hex, +/- numbers, Infinity/NaN). Top-level `$schema` key is ignored/preserved (not a resource... kept in file on write). File re-read on every start. Non-object top level → error exit.
- R3 Mutations persisted to the db file, atomically (write temp file in same dir + rename), as pretty JSON (2-space). Survive restart. For a `.json5` file, output is written as JSON (valid JSON5). Concurrent writes serialized.
### Routes
- R4 Arrays: `GET /posts`, `GET /posts/:id`, `POST /posts`, `PUT /posts/:id`, `PATCH /posts/:id`, `DELETE /posts/:id`. Objects: `GET/PUT/PATCH /profile`.
- R5 README example: `GET /posts/1` → 200 `{"id":"1","title":"a title","views":100}` pretty-printed with 2 spaces.
- R6 Ids are strings. POST without `id` generates unique random string id (not colliding with existing); POST with numeric id coerces to string; POST returns 201 with created item; POST with an existing id → 400 (assumption). Stored id for items lacking one in the db file: loaded items without id are left as is (assumption), id lookup compares as strings (`String(item.id)`).
- R7 PUT replaces item (keeps id from URL, body id ignored); PATCH shallow-merges (id preserved); both 200 with item; unknown id → 404 `{"error":"NotFound"}`. PUT/PATCH on object resource replace/merge, 200. POST on object resource → 404 (not allowed; assumption: 404). Non-object body (array/string) → 400 `{"error":"..."}`; invalid JSON → 400.
- R8 DELETE returns 200 with the deleted item; unknown id → 404. 
- R9 Unknown routes/resources/ids → 404 `{"error":"NotFound"}` (with JSON body, pretty-printed). `GET /` is served by static (index.html) if present, else 404 NotFound JSON. Unsupported method on known route → 404.
- R10 `Content-Type: application/json; charset=utf-8` for JSON responses. Request bodies parsed as JSON (also tolerate form-urlencoded? no — JSON only).
- R11 CORS: `Access-Control-Allow-Origin: *` on all responses; `OPTIONS` preflight → 204 with `Access-Control-Allow-Methods` (GET,HEAD,PUT,PATCH,POST,DELETE), `Access-Control-Allow-Headers` echoing `Access-Control-Request-Headers` (or `*`). HEAD supported.
### Query
- R12 Conditions `field:op=value`, ops: (none)=eq, eq, ne, lt, lte, gt, gte, in (comma list), contains, startsWith, endsWith (case-insensitive string ops). Multiple conditions AND. Dotted nested fields (`author.name`). Unknown op → no match / ignored? (assumption: 400? chosen: treated as no filtering error → 400 not used; unknown op ignored). 
- R13 Type-aware comparison: number field vs numeric string value compares numerically (`views:gt=100`); string fields compare as strings (lt "m"); booleans `true/false`; `null`; `eq` compares by JSON type conversion of the query string (value parsed to field's type); `id:in=1,2,3` matches string ids. A field absent on an item doesn't match (except `ne`, which matches).
- R14 `_sort=a,-b` multi-key, `-` descending, nested fields, numeric and string aware (numbers numerically, strings by code order case-sensitive localeCompare-free), stable; missing values last.
- R15 Pagination `_page`, `_per_page` (default 10 when only `_page` given; also when only `_per_page` given page=1): envelope `{first:1, prev, next, last, pages, items, data}` where items = total count after filtering; `prev/next` null at ends; invalid values (non-numeric, <1) normalized (page<1→1, per_page<1→10; page > pages → last page, with `next` null); empty collection → pages 1? (assumption: pages=0, first=1, last=0... chosen: pages=max(1,..)? We choose first 1, prev null, next null, last 1, pages 1, items 0, data []). Order: filter → sort → paginate. No pagination params → plain array.
- R16 `_embed=comments` on `/posts` (and `/posts/:id`) adds `comments` array of children whose `postId` (`<singular(parent collection)>Id`, singular = strip trailing `s`; `ies`→`y`) equals parent id (string compare). `_embed=post` on `/comments` adds `post` object parent via the item's `postId` (null/absent if none). Multiple `_embed` (repeated or comma-separated); dotted not required. Unknown embed ignored. Embedding applies before filter-nothing; embedded data not persisted.
- R17 `_where` JSON: `{"field":{"op":val}}`, nested objects for nested fields (`{"author":{"name":{"lt":"m"}}}`), `and`/`or` arrays, `not` object. README example works. When valid, it overrides normal condition query params; when invalid JSON → ignored (normal params used). `_sort`, pagination, `_embed` still apply with it.
- R18 `DELETE /posts/1?_dependent=comments` deletes the item and all `comments` whose `postId` equals the id (comma list allowed); unknown dependent collection ignored. Persisted.
### Static / misc
- R19 `--static dir` (repeatable) serves files with standard MIME types; default `./public` if it exists. Path traversal blocked. API routes take precedence over static files? (assumption: static served first only if file exists and no resource named same segment... chosen: static checked for GET/HEAD when path is not an API resource).
- R20 Responses never leak internals; malformed percent-encoding → 400; server never crashes on bad input.
- R21 Performance: 10,000-item collection filtered/sorted/paginated in well under 1s; persisted writes coalesced serially.
### Deliverables
- R22 `serve` executable, `package.json` (no deps, `npm test`), test-suite covering every README example, README.md (install/run/test/design).

## Assumptions
Listed inline above ("assumption"). Node chosen because spec comes from the Node ecosystem; JSON5 parser hand-written. Spec silent on error bodies other than NotFound: `{"error":"<Message>"}`.

## Test strategy
`node:test` with real HTTP against a server spawned on port 0 via module API and copy of fixture db in tmp dir: R4–R18 route/query tests (every README example); persistence/restart tests by spawning `./serve` (R1–R3); JSON5 parser unit tests (R2); static/CORS tests (R11,R19); perf test (R21).
