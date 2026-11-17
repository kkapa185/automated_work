# CONDUIT-1: Backend for "Conduit", a Medium.com-style blogging platform (RealWorld API spec)

Implement the complete backend REST API of Conduit. The authoritative contract is the OpenAPI document
in `spec/openapi.yml` (endpoints, request/response JSON shapes, status codes, error formats); follow it
exactly. Summary:

* Users & auth: `POST /api/users` (register, 201), `POST /api/users/login`, `GET /api/user`,
  `PUT /api/user` (partial update; empty-string `bio`/`image` normalise to `null`, `null` accepted for
  nullable fields). JWT auth via header `Authorization: Token <jwt>`. Passwords hashed (bcrypt/argon2/scrypt).
* Profiles: `GET /api/profiles/:username`, `POST`/`DELETE /api/profiles/:username/follow`.
* Articles: list with filters `tag`, `author`, `favorited`, `limit` (default 20), `offset` (default 0),
  most recent first, `articlesCount` = total matching; `GET /api/articles/feed` (followed authors only);
  `GET/PUT/DELETE /api/articles/:slug`; `POST /api/articles` (201; unique slug derived from the title);
  list responses omit `body`; `favorited`, `favoritesCount`, `author.following` computed for the caller;
  tags returned in their stored order.
* Comments: `GET/POST /api/articles/:slug/comments`, `DELETE /api/articles/:slug/comments/:id`.
* Favorites: `POST`/`DELETE /api/articles/:slug/favorite`. Tags: `GET /api/tags`.
* Errors: `401` for missing/invalid auth, `403` when acting on another user's article/comment, `404` for
  unknown resources, `409` for duplicate username/email on register/update, `422` for validation errors —
  body `{"errors": {"<field>": ["<message>", ...]}}`.
* Timestamps ISO-8601 with milliseconds and `Z`.

Runtime contract: `./serve --port <port>` starts the server on 127.0.0.1 with a fresh, self-initialising
database (SQLite file or in-memory; no external services), ready within 30 seconds, serving the API
under `/api`. Any mainstream stack is fine. Provide automated integration tests covering every endpoint
and error case, and a README.
