# Benchmark report — typicode/json-server (v1 beta)

**Ticket:** [`task.md`](task.md) (API-21). It asks for a REST API generated from a JSON file: collections and
singletons, condition operators, sorting, pagination, embeds, `_where`, cascading deletes, persistence.
The project README was provided as the normative input.

**Reference execution:** json-server built from the repo (`lib/bin.js`). The hidden harness
[`compare.py`](compare.py) replays the same 46 requests against the same `db.json`, including mutations.
It masks server-generated ids, then compares status codes and bodies, CORS, the persisted file, and the
state after a restart.

## Score history
| attempt | score | cause |
|---|---|---|
| 1 | 0.76 | **My ticket errors.** My probe had stripped spaces from the output, so the ticket said `{"error": "NotFound"}` where the reference returns `"Not Found"`. The ticket also omitted three real behaviours: POST ignores client-supplied ids; `_sort` is case-insensitive; deleting a parent nulls the children's foreign keys. |
| 2 | **0.98** | Only the byte-level layout of the persisted `db.json` differs. |

**Reference-vs-documentation conflicts:** the README documents `id:in=1,3` and `_where` with `and`, but the
reference returns `[]` for both. The generated server followed the documentation. Those two requests were
removed from the hidden corpus, because the ticket makes the documentation normative.

**Harness fix:** the reference persists asynchronously, so the harness now waits for writes to settle.
It self-checks at 1.0 three times in a row.

**Process (attempt 2):** 4 turns. $1.08.
