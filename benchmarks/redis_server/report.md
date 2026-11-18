# Benchmark report — redis/redis

**Ticket:** [`task.md`](task.md) (KV-6379). It asks for a Redis-compatible server: RESP2 with pipelining, all
core data types, expiry, `MULTI/EXEC/WATCH`, pub/sub, blocking pops, snapshots that survive restart, and
throughput of at least 10k requests/s.

**Reference execution:** `redis-server` built from the repo. The hidden harness [`compare.py`](compare.py)
does three things:
- replays an identical script of about 190 commands through both servers over raw RESP, covering
  strings, lists, hashes, sets, sorted sets, keys, expiry, databases, transactions, type errors and
  argument errors. Replies must be identical, comparing only the class of each error and the members of
  unordered replies;
- runs scenarios on both: expiry timing, pub/sub with patterns, `BLPOP` handoff and timeout, `WATCH`
  conflicts, a 100-command pipeline, 50 concurrent clients, and `SAVE` + restart;
- measures throughput with the repo's `redis-benchmark`.

## Result (attempt 1): **score 1.00 (164/164)**
Every reply and every scenario matches the real Redis. Throughput is **14.9k (SET) / 18.8k (GET)
requests/s** from a single client. The implementation is in Go.

**Process:** milestone mode, 8 turns on one session. $6.26. The run included a usage-limit pause and
two VM reboots; the task resumed on its stored session each time.
