# KV-6379: A Redis-compatible in-memory data-structure server

Build a network server compatible with Redis clients (any language; no Redis/Valkey/KeyDB/Dragonfly
code, embedded Redis, or RESP-server frameworks that implement commands for you). Runtime contract:
`./serve --port <port> [--dir <data-dir>]` listens on 127.0.0.1 and speaks the Redis protocol (RESP2,
including inline commands and pipelining) to any number of concurrent clients. Redis' official command
documentation is the normative reference for reply types, error messages and edge cases.

Commands (semantics, reply types and error replies exactly as Redis, e.g. `-ERR wrong number of arguments
for 'get' command`, `-WRONGTYPE Operation against a key holding the wrong kind of value`, integers vs bulk
strings vs nil vs arrays):
* Connection/server: `PING ECHO SELECT (16 databases) DBSIZE FLUSHDB FLUSHALL INFO (sections, any
  content) TIME QUIT COMMAND (minimal) CONFIG GET/SET (minimal) SAVE BGSAVE LASTSAVE`.
* Keys: `DEL EXISTS TYPE KEYS (glob patterns) SCAN (cursor, MATCH, COUNT, TYPE) RENAME RENAMENX MOVE
  RANDOMKEY EXPIRE PEXPIRE EXPIREAT PEXPIREAT TTL PTTL PERSIST UNLINK COPY OBJECT ENCODING` with lazy and
  active expiry.
* Strings: `GET SET (EX PX EXAT PXAT NX XX KEEPTTL GET) SETNX SETEX PSETEX MGET MSET MSETNX GETSET GETDEL
  GETEX APPEND STRLEN INCR DECR INCRBY DECRBY INCRBYFLOAT GETRANGE SETRANGE` (integer/float parsing and
  overflow errors as Redis).
* Lists: `LPUSH RPUSH LPUSHX RPUSHX LPOP RPOP (count) LLEN LRANGE LINDEX LSET LINSERT LREM LTRIM LPOS
  RPOPLPUSH LMOVE BLPOP BRPOP (blocking with timeout, served in FIFO order)`.
* Hashes: `HSET HGET HMSET HMGET HGETALL HDEL HEXISTS HLEN HKEYS HVALS HINCRBY HINCRBYFLOAT HSETNX
  HSTRLEN HRANDFIELD`.
* Sets: `SADD SREM SMEMBERS SISMEMBER SMISMEMBER SCARD SPOP SRANDMEMBER SINTER SUNION SDIFF SINTERSTORE
  SUNIONSTORE SDIFFSTORE SMOVE SINTERCARD`.
* Sorted sets: `ZADD (NX XX GT LT CH INCR) ZREM ZSCORE ZMSCORE ZINCRBY ZCARD ZCOUNT ZRANK ZREVRANK
  ZRANGE (BYSCORE BYLEX REV LIMIT WITHSCORES, exclusive/infinite bounds) ZREVRANGE ZRANGEBYSCORE
  ZREVRANGEBYSCORE ZRANGEBYLEX ZPOPMIN ZPOPMAX ZUNIONSTORE ZINTERSTORE (WEIGHTS AGGREGATE)`; scores
  printed like Redis (e.g. `1.5`, `3`, `inf`).
* Transactions: `MULTI EXEC DISCARD WATCH UNWATCH` (queued replies, `EXECABORT`, optimistic locking).
* Pub/Sub: `SUBSCRIBE UNSUBSCRIBE PSUBSCRIBE PUNSUBSCRIBE PUBLISH PUBSUB CHANNELS/NUMSUB` with the
  exact push-message format.
* Persistence: `SAVE`/`BGSAVE` write a snapshot into `--dir` (format of your choice) that is loaded at
  start-up, so data and remaining TTLs survive a restart.
* Performance: at least ~10,000 simple GET/SET requests per second from a single client, and correct
  behaviour with 50 concurrent clients.

Deliverables: the server, a test-suite (protocol, every command family, expiry, transactions, pub/sub,
persistence, concurrency), and a README.
