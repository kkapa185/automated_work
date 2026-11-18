# KV-6379 — a Redis-compatible in-memory data-structure server

A from-scratch server written in Go (standard library only, no third-party code) that speaks the Redis protocol
(RESP2: multi-bulk **and inline** commands, pipelining) on `127.0.0.1` to any number of concurrent clients.
Works with `redis-cli`, `redis-py`, `go-redis`, etc.

## Install / run
Requires Go ≥ 1.24 (nothing else; there are no dependencies to install).

```
./serve --port 6380 [--dir ./data]     # builds bin/kvserver on first use (or when sources changed), then runs it
redis-cli -p 6380 set foo bar
```
* `--port` TCP port (default 6379); the server always binds `127.0.0.1`.
* `--dir` directory for the snapshot file `dump.kvdb` (created if missing). Default: current working directory.
  If `--dir` is given, SIGINT/SIGTERM also write a final snapshot (without `--dir`, only an explicit `SAVE`/`BGSAVE` writes).
* `make build` builds `bin/kvserver` explicitly.

## Tests
```
make test     # go vet + unit tests (internal/server) + black-box tests (tests/)
make race     # the same, with BOTH the tests and the server binary built with the race detector
tests/smoke.sh  # start ./serve and talk raw RESP to it
```
The black-box tests (`tests/`) build the real binary, start it on a random port with a temp data dir and talk RESP over TCP
with a tiny hand-written client. They cover: protocol (inline, pipelining, split packets, binary-safe/large payloads, protocol
errors), every command family, expiry (lazy + active), transactions, pub/sub (byte-exact wire format), blocking commands,
persistence (SAVE/BGSAVE/restart/SIGTERM/corruption/TTL survival), and concurrency/throughput (single client ≥ 10k req/s,
50 concurrent clients, mixed-type workloads, 300 idle connections + churn, huge unread pipelines, pathological globs,
100k-element collections). Expected values are computed from the Redis command documentation, not copied from the server.
Unit tests cover glob matching, integer/float parsing & formatting, RESP parsing, the skip list (differential test against a
naive model), and snapshot round-trip/corruption handling.

## Supported commands
* **Connection/server**: PING ECHO SELECT(16 dbs) DBSIZE FLUSHDB FLUSHALL INFO TIME QUIT COMMAND CONFIG(GET/SET/RESETSTAT/REWRITE)
  CLIENT(ID/SETNAME/GETNAME/INFO/LIST) HELLO(2 only) RESET SAVE BGSAVE LASTSAVE SHUTDOWN
* **Keys**: DEL UNLINK EXISTS TOUCH TYPE KEYS SCAN(MATCH/COUNT/TYPE) RENAME RENAMENX MOVE RANDOMKEY EXPIRE PEXPIRE EXPIREAT
  PEXPIREAT (NX/XX/GT/LT) TTL PTTL EXPIRETIME PEXPIRETIME PERSIST COPY(DB/REPLACE) OBJECT(ENCODING/REFCOUNT/IDLETIME/FREQ)
* **Strings**: GET SET(EX PX EXAT PXAT NX XX KEEPTTL GET) SETNX SETEX PSETEX MGET MSET MSETNX GETSET GETDEL GETEX APPEND STRLEN
  INCR DECR INCRBY DECRBY INCRBYFLOAT GETRANGE SUBSTR SETRANGE
* **Lists**: LPUSH RPUSH LPUSHX RPUSHX LPOP RPOP(count) LLEN LRANGE LINDEX LSET LINSERT LREM LTRIM LPOS RPOPLPUSH LMOVE
  BLPOP BRPOP BLMOVE BRPOPLPUSH
* **Hashes**: HSET HGET HMSET HMGET HGETALL HDEL HEXISTS HLEN HKEYS HVALS HINCRBY HINCRBYFLOAT HSETNX HSTRLEN HRANDFIELD
* **Sets**: SADD SREM SMEMBERS SISMEMBER SMISMEMBER SCARD SPOP SRANDMEMBER SINTER SUNION SDIFF SINTERSTORE SUNIONSTORE
  SDIFFSTORE SMOVE SINTERCARD
* **Sorted sets**: ZADD(NX XX GT LT CH INCR) ZREM ZSCORE ZMSCORE ZINCRBY ZCARD ZCOUNT ZLEXCOUNT ZRANK ZREVRANK(WITHSCORE)
  ZRANGE(BYSCORE BYLEX REV LIMIT WITHSCORES) ZREVRANGE ZRANGEBYSCORE ZREVRANGEBYSCORE ZRANGEBYLEX ZREVRANGEBYLEX ZPOPMIN ZPOPMAX
  ZREMRANGEBYRANK/SCORE/LEX ZUNIONSTORE ZINTERSTORE(WEIGHTS AGGREGATE)
* **Transactions**: MULTI EXEC DISCARD WATCH UNWATCH
* **Pub/Sub**: SUBSCRIBE UNSUBSCRIBE PSUBSCRIBE PUNSUBSCRIBE PUBLISH PUBSUB(CHANNELS/NUMSUB/NUMPAT)

## Design
* **Execution model.** One goroutine per connection parses RESP; commands execute under one global mutex, giving Redis-like
  atomicity for every command and for whole MULTI/EXEC blocks. Replies are buffered per client and flushed right before the
  reader would block (so pipelines are answered in large writes); a writer goroutine per client does the socket I/O, so a slow
  reader never blocks the executor (its queue is capped at 256 MB, then it is disconnected).
* **Keyspace.** Per database: `map[key]*entry` + a dense key slice (SCAN walks it top-down, so deletions can never hide a key
  that existed for the whole iteration) + a TTL map. Expiry is lazy on every access path plus an active sampler (every 100 ms,
  Redis-style adaptive loop).
* **Types.** Lists are deques (O(1) both ends); hashes keep insertion order (tombstones + compaction); sets are dense slice +
  index (O(1) add/remove/random pick); sorted sets are a member→score map + an indexable skip list with spans (O(log n) add,
  remove, rank, select, range). `OBJECT ENCODING` mimics Redis 7 thresholds (listpack/quicklist/hashtable/intset/skiplist),
  adjustable through `CONFIG SET`.
* **Numbers.** Integers parse strictly like Redis (no `+`, whitespace, leading zeros). INCRBYFLOAT/HINCRBYFLOAT use 64-bit-
  mantissa arithmetic (`math/big`) to reproduce Redis' long-double results (`0.1 + 0.2 → 0.3`). Scores print as the shortest
  round-trip decimal (`1.5`, `3`, `inf`).
* **Blocking commands.** A blocked client is parked in a per-key FIFO queue; whichever command makes data available serves the
  waiters (atomically, in arrival order). The parked connection is watched so a disconnect never swallows an element.
  Inside MULTI/EXEC blocking commands behave as non-blocking.
* **Transactions.** Queued per client; WATCH stores a fingerprint per key (entry identity, expiry, modification counters), compared
  at EXEC: any real write — even of an identical value — or expiry/deletion aborts; no-op writes (e.g. SADD of an existing
  member) do not.
* **Pub/Sub.** Registries per channel and pattern; PUBLISH pre-encodes the push once and appends it to each subscriber's output
  queue. Subscribed connections accept only (P)(UN)SUBSCRIBE / PING / QUIT / RESET.
* **Persistence.** `SAVE` serialises the whole dataset under the lock and writes `dump.kvdb` via temp-file + fsync + atomic
  rename. `BGSAVE` serialises a consistent point-in-time image under the lock, then writes the file in the background (a
  second BGSAVE meanwhile gets `ERR Background save already in progress`). Format: magic `KVDB`+version, per-database
  typed entries with **absolute** expiry timestamps (so remaining TTLs survive downtime; already-expired keys are dropped),
  trailing CRC-32. At start the snapshot is loaded; a missing file means an empty start and a corrupt/truncated file is logged
  and ignored (never crashes, never partially loads).
* **Glob matching** is iterative with single-star backtracking (O(len(p)·len(s))), immune to exponential patterns.

## Assumptions & limits
See `.orchestrator/requirements.md`. Highlights: RESP2 only (`HELLO 3` → `-NOPROTO`); no Lua, replication, ACL, streams,
sharded pub/sub or HSCAN/SSCAN; max bulk 512 MB, max inline request 64 KB; snapshot format is private to this project.
