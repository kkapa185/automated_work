# Benchmark report — gothinkster/realworld (Conduit API)

**Ticket:** [`task.md`](task.md) (CONDUIT-1). It asks for the full Conduit backend. The workspace received the
official `openapi.yml` contract, but *not* the conformance tests.

**Reference execution:** the official RealWorld conformance collection: the Bruno collection generated
from the project's Hurl suite, 157 requests with assertions across auth, profiles, articles, comments,
favorites, feed, pagination, tags and every error category. The hidden harness [`compare.py`](compare.py)
starts `./serve --port N` and runs every folder with the Bruno CLI.

## Result (attempt 1): score 0.99 (156/157 requests pass)
The only failure is `errors-auth/21`: updating to a password shorter than 8 characters must return 422.
That rule exists only in the test suite; `openapi.yml` sets no minimum length. So 156/157 is the
ceiling reachable from the provided contract.

**Process:** 4 turns on one session: plan → implement → review (GAPS_FIXED) → review (PASS). $0.65, 6 min.
