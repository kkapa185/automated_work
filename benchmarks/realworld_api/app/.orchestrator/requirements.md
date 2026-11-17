# Conduit backend — requirements

## Product
A REST backend for "Conduit" (Medium-style blogging platform) following `spec/openapi.yml` (RealWorld API 2.0).
Python 3 standard library only (http.server threaded, sqlite3, hmac/hashlib: scrypt for passwords, HS256 JWT hand-rolled),
started with `./serve --port <port>`, binding 127.0.0.1, fresh self-initialising SQLite DB (in-memory/temp), API under `/api`.

## Acceptance criteria
R1. `./serve --port P` listens on 127.0.0.1:P, ready <30s, fresh empty DB each start, no external services.
R2. `POST /api/users` `{"user":{username,email,password}}` -> 201 `{"user":{email,token,username,bio:null,image:null}}`.
R3. Register validation -> 422 `{"errors":{field:[msg]}}`: missing/blank username/email/password ("can't be blank"), malformed email ("is invalid"), malformed body/missing `user` object (422).
R4. Duplicate username or email on register -> 409 `{"errors":{"username":["has already been taken"]}}` (field = offending one; email compare case-insensitive).
R5. `POST /api/users/login` -> 200 user object with token; wrong password/unknown email -> 401 (errors body); missing fields -> 422.
R6. Auth: header `Authorization: Token <jwt>`; missing/malformed/invalid/expired token or deleted user on protected endpoints -> 401 `{"errors":{"token":["is missing"|"is invalid"]}}`. Optional-auth endpoints (profile get, article list/get, comments get) work without token; an invalid token supplied there -> 401.
R7. `GET /api/user` -> 200 current user. `PUT /api/user` partial update of email/username/password/bio/image; `""` bio/image -> null; null accepted for bio/image; response 200 user (with token). Duplicate username/email (of another user) -> 409; invalid email/blank username/blank password -> 422; empty `user` object or no updatable field -> 422; setting own current values is OK. Updated password works for login, old does not.
R8. `GET /api/profiles/:username` -> `{"profile":{username,bio,image,following}}`; 404 `{"errors":{"profile":["not found"]}}` unknown.
R9. `POST/DELETE /api/profiles/:username/follow` (auth) -> 200 profile with following true/false; idempotent; 404 unknown; 401 no auth. Following oneself allowed? Assumption: allowed (no spec prohibition).
R10. `POST /api/articles` (auth) `{"article":{title,description,body,tagList?}}` -> 201 `{"article":{slug,title,description,body,tagList,createdAt,updatedAt,favorited:false,favoritesCount:0,author:{username,bio,image,following:false}}}`. Missing/blank title/description/body -> 422 ("can't be blank"); tagList must be an array of strings else 422. 401 w/o auth.
R11. Slug derived from title (lowercase, non-alnum runs -> '-', trimmed); unique: on collision append `-2`, `-3`, … ; a title with no sluggable chars falls back to "article". Duplicate titles are allowed (never 409).
R12. `GET /api/articles/:slug` -> 200 article (with body); 404 `{"errors":{"article":["not found"]}}`. Computes favorited/following for the caller.
R13. `PUT /api/articles/:slug` (auth, author only) partial update title/description/body/tagList; updatedAt changes; title change regenerates slug (unique, excluding itself; unchanged if title unchanged); 403 `{"errors":{"article":["forbidden"]}}` for non-author; 404 unknown; 401 no auth; blank string fields -> 422; empty update object -> 422... Assumption: empty `article` object is a no-op returning 200 is NOT chosen; we return 422.  Check order: 401, 404, 403, 422.
R14. `DELETE /api/articles/:slug` (auth, author) -> 204 empty body; removes comments and favorites too; 403 non-author; 404; 401.
R15. `GET /api/articles`: filters `tag`, `author` (username), `favorited` (username), combinable (AND); `limit` default 20, `offset` default 0; order newest first (createdAt desc, id desc tiebreak); response `{"articles":[...],"articlesCount":N}` with N total matching (ignoring limit/offset); articles omit `body`; unknown author/tag/favorited user -> empty list, count 0. Invalid limit (non-int, <1) or offset (non-int, <0) -> 422.
R16. `GET /api/articles/feed` (auth required, 401 otherwise): only articles by followed users, same pagination/shape/ordering.
R17. `tagList` returned in stored (insertion) order; duplicates within a submitted tagList are removed keeping first occurrence order. `GET /api/tags` -> `{"tags":[...]}` all distinct tags in use (by first-appearance order); tags of deleted articles disappear.
R18. Comments: `POST /api/articles/:slug/comments` `{"comment":{"body"}}` (auth) -> 201 `{"comment":{id,createdAt,updatedAt,body,author}}`; blank/missing body 422; 404 unknown article; 401. `GET` -> `{"comments":[...]}` ordered oldest first (id asc), author.following per caller; 404 unknown article. `DELETE /api/articles/:slug/comments/:id` -> 204; 403 not comment author; 404 unknown article or comment (also comment belonging to another article); non-integer id -> 422; 401.
R19. Favorites: `POST/DELETE /api/articles/:slug/favorite` (auth) -> 200 article with favorited & favoritesCount updated; idempotent (no double count); 404; 401. `favorited` filter lists articles favorited by that user.
R20. Timestamps ISO-8601 UTC with milliseconds and `Z` (e.g. `2024-01-02T03:04:05.678Z`).
R21. Passwords never stored/returned in plain text (scrypt with per-user salt).
R22. Error bodies always `{"errors":{field:[msgs]}}`; unknown route -> 404 errors body; unsupported method -> 405; invalid JSON -> 422. All JSON responses `Content-Type: application/json`. CORS headers permitted + OPTIONS preflight 204.
R23. Check order on protected routes: 401 (auth) before 404/403/422 body validation, except 404 for unknown resource precedes 403 and 422 body validation.
R24. Concurrency-safe (threaded server, single sqlite connection guarded by lock, foreign keys on).
R25. Deliverables: `serve` executable, `tests/` integration tests (pytest, start real server subprocess on a free port) covering every endpoint & error case, `README.md`, `requirements-dev.txt`/pyproject with pytest, requests-free (use urllib/http.client).

## Assumptions
- Stack: Python stdlib only for runtime (nothing to install); pytest for tests.
- Username: non-blank string; no other format rules. Password: any non-blank (no min length). Email: simple regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`.
- Token expiry 30 days; secret random per process start.
- Login with unknown email -> 401 (not 404), body `{"errors":{"email or password":["is invalid"]}}`.
- Profile `following` false when unauthenticated.
- Spec lists 401 for GET /articles etc. only for invalid tokens.
- Tags stored per-article with position; tags endpoint returns global order of first appearance.

## Test strategy
Black-box pytest integration tests against a real `./serve` subprocess: one test module per resource (users/auth, profiles, articles, feed/pagination/filters, comments, favorites, tags, errors/format). Covers R1–R24. Pure unit tests for slugify, JWT and timestamp format.
