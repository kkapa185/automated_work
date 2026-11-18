# KV-6379 requirements

## Product
A Redis-compatible in-memory data-structure server written in Go (stdlib only, no dependencies). `./serve --port <p> [--dir <d>]`
(a shell wrapper that builds `bin/kvserver` with `go build` if missing/stale, then execs it) listens on 127.0.0.1 and speaks RESP2
(multi-bulk and inline commands, pipelining) to many concurrent clients. It implements the string, list, hash, set, sorted-set, key,
transaction, pub/sub, server and persistence command families listed in the ticket with Redis' reply types and error messages.

## Architecture (decision)
One goroutine per connection parses RESP and submits commands to a single global executor (a mutex-protected `Server.exec`, giving
Redis-like atomicity for commands, MULTI/EXEC, and Lua-free scripts). Blocking commands (BLPOP/BRPOP) park the client on a per-key FIFO
wait queue and are woken by pushes under the same lock. Expiry: lazy on access + active sampling goroutine every 100ms.
Persistence: snapshot file `dump.kvdb` (own binary format, written to temp file then atomically renamed) in `--dir`; loaded at start.

## Acceptance criteria
R1  CLI: `./serve --port N [--dir D]` binds 127.0.0.1:N; default dir is cwd; unknown flags ignored/err clearly; works from clean checkout.
R2  RESP2 parsing: multi-bulk, inline commands (space-separated, quotes `"..."`/`'...'` with escapes), blank lines ignored, pipelining of many
    commands in one packet answered in order, binary-safe bulk strings, large payloads (>1MB); protocol errors reply `-ERR Protocol error: ...` and close.
R3  Replies: simple string, error, integer, bulk, nil bulk (`$-1`), nil array (`*-1`), arrays, nested arrays. Unknown command:
    `-ERR unknown command 'x', with args beginning with: ...`. Arity errors: `-ERR wrong number of arguments for 'get' command` (lowercase name).
    Wrong type: `-WRONGTYPE Operation against a key holding the wrong kind of value`. Syntax: `-ERR syntax error`.
    Non-integer: `-ERR value is not an integer or out of range`; non-float: `-ERR value is not a valid float`.
R4  Connection/server: PING [msg], ECHO, SELECT 0-15 (`-ERR DB index is out of range`), DBSIZE, FLUSHDB, FLUSHALL, INFO [section] (server, clients,
    memory, stats, replication, keyspace, ... any content, `# Section` / `key:value` lines, keyspace `db0:keys=N,expires=M,avg_ttl=0`), TIME, QUIT (+OK then close),
    COMMAND (COUNT, minimal list/INFO/DOCS empty ok), CONFIG GET (glob, e.g. dir, save, appendonly, maxmemory...) / SET (accept & store any param) / RESETSTAT,
    SAVE, BGSAVE (`+Background saving started`), LASTSAVE, CLIENT SETNAME/GETNAME/ID minimal, HELLO not required (reply error for proto 3).
R5  Keys: DEL, EXISTS (multi, duplicates counted), TYPE (string/list/hash/set/zset/none), KEYS glob (`* ? [abc] [a-z] [^a] \x`), SCAN cursor/MATCH/COUNT/TYPE
    (full iteration returns every key at least once, terminates with cursor 0), RENAME (`-ERR no such key`), RENAMENX, MOVE (0 if exists in dest / same db error),
    RANDOMKEY, EXPIRE/PEXPIRE/EXPIREAT/PEXPIREAT (NX/XX/GT/LT options; return 1/0; non-positive deletes key), TTL/PTTL (-2 missing, -1 no expire), PERSIST, UNLINK,
    COPY (DB, REPLACE; deep copy incl. TTL), OBJECT ENCODING (int/embstr/raw, listpack/quicklist/hashtable/intset/skiplist) and OBJECT REFCOUNT/IDLETIME/FREQ minimal, TOUCH.
R6  Expiry: lazy expiry on every access path; active expiry removes expired keys without access (DBSIZE/KEYS/INFO eventually reflect it); rename/copy preserve TTL; SET clears TTL unless KEEPTTL.
R7  Strings: GET, SET with EX PX EXAT PXAT NX XX KEEPTTL GET (conflicting options -> syntax error; invalid expire -> `-ERR invalid expire time in 'set' command`; SET NX GET ok; GET on non-string WRONGTYPE),
    SETNX, SETEX, PSETEX, MGET (non-strings -> nil), MSET (odd args -> `wrong number of arguments for 'mset' command`), MSETNX (atomic), GETSET, GETDEL, GETEX (EX PX EXAT PXAT PERSIST),
    APPEND, STRLEN, INCR/DECR/INCRBY/DECRBY (64-bit overflow -> `-ERR increment or decrement would overflow`), INCRBYFLOAT (Redis %.17g-trimmed formatting, NaN/Inf error `-ERR increment would produce NaN or Infinity`),
    GETRANGE (negative idx, out of range -> ""), SETRANGE (zero-padding, offset negative error, max 512MB `-ERR string exceeds maximum allowed size (proto-max-bulk-len)`), SUBSTR alias optional, LCS not required.
R8  Lists: LPUSH, RPUSH (multi values), LPUSHX, RPUSHX, LPOP/RPOP [count] (count 0 -> empty array, missing key with count -> nil array), LLEN, LRANGE, LINDEX, LSET (`-ERR no such key`, `-ERR index out of range`),
    LINSERT BEFORE|AFTER (-1 pivot missing, 0 key missing), LREM (count sign), LTRIM, LPOS (RANK COUNT MAXLEN), RPOPLPUSH, LMOVE (LEFT/RIGHT combos),
    BLPOP/BRPOP (multi-key, timeout seconds incl. float and 0 = forever, `-ERR timeout is not a float or out of range`, FIFO among waiting clients, nil array on timeout, reply `[key, value]`),
    BLMOVE/BRPOPLPUSH (bonus). Empty lists are deleted. Blocked client inside MULTI behaves as non-blocking.
R9  Hashes: HSET (multi pairs, returns number of new fields), HGET, HMSET (+OK), HMGET, HGETALL, HDEL, HEXISTS, HLEN, HKEYS, HVALS, HINCRBY (`-ERR hash value is not an integer`), HINCRBYFLOAT (`-ERR hash value is not a float`),
    HSETNX, HSTRLEN, HRANDFIELD (count sign semantics, WITHVALUES), HSCAN (bonus). Empty hashes are deleted.
R10 Sets: SADD, SREM, SMEMBERS, SISMEMBER, SMISMEMBER, SCARD, SPOP [count], SRANDMEMBER [count] (negative count allows repeats), SINTER, SUNION, SDIFF, SINTERSTORE, SUNIONSTORE, SDIFFSTORE
    (empty result deletes dest), SMOVE, SINTERCARD numkeys keys... [LIMIT n] (`-ERR numkeys should be greater than 0`), SSCAN (bonus). Missing keys = empty sets; wrong type -> WRONGTYPE.
R11 Sorted sets: ZADD (NX XX GT LT CH INCR; NX+XX / GT+LT+NX incompatibilities -> specific Redis errors; INCR single pair; nil reply when INCR blocked), ZREM, ZSCORE, ZMSCORE, ZINCRBY, ZCARD, ZCOUNT,
    ZRANK/ZREVRANK (WITHSCORE optional), ZRANGE (BYSCORE BYLEX REV LIMIT WITHSCORES; exclusive `(`, `-inf`/`+inf`, lex `[`,`(`,`-`,`+`), ZREVRANGE, ZRANGEBYSCORE, ZREVRANGEBYSCORE, ZRANGEBYLEX, ZREVRANGEBYLEX,
    ZPOPMIN/ZPOPMAX [count], ZUNIONSTORE/ZINTERSTORE (numkeys, WEIGHTS, AGGREGATE SUM|MIN|MAX; sets accepted as score 1), ZREMRANGEBYSCORE/RANK/LEX, ZLEXCOUNT (bonus). Score formatting like Redis: `1.5`, `3`, `inf`, `-inf`,
    shortest round-trip %.17g style. Ordering by (score, member bytes). Error `-ERR min or max is not a float`, `-ERR min or max not valid string range item`, `-ERR value is not a valid float`.
R12 Transactions: MULTI (nested -> `-ERR MULTI calls can not be nested`), queued reply `+QUEUED`, EXEC returns array of replies (runtime errors inside appear as error elements, not abort), EXEC without MULTI error,
    DISCARD, syntax/arity/unknown-command error at queue time -> `-EXECABORT Transaction discarded because of previous errors.`, WATCH/UNWATCH (key modified/expired/deleted/flushed by any client -> EXEC returns nil array; WATCH inside MULTI error), commands atomic.
R13 Pub/Sub: SUBSCRIBE/UNSUBSCRIBE/PSUBSCRIBE/PUNSUBSCRIBE reply `[subscribe, chan, count]` per channel (unsubscribe with no args -> all, or `[unsubscribe, nil, 0]`), messages `[message, chan, payload]`,
    `[pmessage, pattern, chan, payload]`, PUBLISH returns receiver count (pattern + direct each counted), subscriber mode restricts commands (`-ERR Can't execute 'get': only (P|S)SUBSCRIBE / (P|S)UNSUBSCRIBE / PING / QUIT / RESET are allowed in this context`), PING in subscribe mode returns `[pong, ""]`,
    PUBSUB CHANNELS [pattern], NUMSUB, NUMPAT. Slow subscriber must not block publishers or other clients (buffered per-client output queue).
R14 Persistence: SAVE writes snapshot synchronously into `--dir` (atomic temp+rename); BGSAVE writes in background goroutine from a consistent copy, replies `+Background saving started`; LASTSAVE unix seconds;
    on start, snapshot loaded (all DBs, all 5 types, absolute expiry times so remaining TTL survives restart; already-expired keys dropped). Missing/corrupt file -> start empty with log (corrupt: don't crash). Optional save on SHUTDOWN not required; SIGTERM/SIGINT saves snapshot if `--dir` was given (assumption).
R15 Performance/concurrency: >=10,000 simple GET/SET/s from a single synchronous client (target >50k, pipelined >500k); 50+ concurrent clients get correct results (e.g., INCR from 50 clients yields exact sum); no data races (`go test -race`).
R16 Case-insensitive command names/options; command args binary safe; integer args parsed strictly (no whitespace, no overflow).
R17 Deliverables: Go test suite (black-box tests spawn built server on a random port, own minimal RESP client) covering protocol, each command family, expiry, transactions, pub/sub, persistence (restart), concurrency/performance; unit tests for glob, score formatting, RESP parsing; README (overview, build/run/test, design, assumptions); `Makefile` with `build`, `test`.
R18 Every concrete ticket example is a test: `-ERR wrong number of arguments for 'get' command`, `-WRONGTYPE Operation against a key holding the wrong kind of value`, score printing `1.5`, `3`, `inf`.

## Assumptions
- Go 1.24 stdlib only; no go.sum deps. `./serve` builds on demand. Behavior targeted at Redis 7.x semantics (e.g., ZRANK WITHSCORE, SINTERCARD, LMOVE, GETEX, EXPIRE NX/XX/GT/LT).
- RESP2 only; HELLO 3 replies `-NOPROTO`. No replication, Lua, ACL, streams, bitmaps, HyperLogLog, geo. Unknown commands error.
- Encodings reported with Redis 7 defaults (listpack up to 128 entries/64 bytes, intset for all-integer sets up to 512, skiplist beyond thresholds).
- SIGTERM saves a snapshot only if `--dir` was passed explicitly.
- Max bulk length 512MB, max inline 64KB.

- ZRANK/ZREVRANK WITHSCORE on a missing member replies a nil array; ZUNION/ZINTER (non-store) and ZRANGESTORE are not implemented (not in the ticket).

- RESET is implemented (clears MULTI/WATCH/subscriptions, SELECT 0). SSUBSCRIBE/SPUBLISH (sharded pub/sub) are not implemented.

## Test strategy
- Go unit tests (package-level): glob matcher, score/float formatting, RESP reader, inline splitting (R2, R5, R11).
- Black-box integration tests (`tests/` package) spawning the binary: per-family files — protocol, keys, strings, lists (incl. blocking FIFO), hashes, sets, zsets, tx, pubsub, expiry, persistence (SAVE + kill + restart; BGSAVE; TTL survives), concurrency/perf (R1–R16, R18).
- Expected values computed by hand from Redis docs (not copied from own output); optional cross-check with `/usr/bin/redis-cli` as client only if present.
