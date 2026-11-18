# DB-1000 — an embeddable SQL engine with a `sqlite3`-compatible shell

A relational database engine written from scratch in Python 3 (standard library only — no `sqlite3`
module, no SQL parser libraries) plus `./sqldb [DATABASE_FILE]`, a shell that reads SQL and dot-commands
from stdin exactly like `sqlite3` fed a script. SQL dialect and semantics follow SQLite.

## Install / run / test
```
python3 --version            # Python 3.9+; no dependencies to install
echo "select 1+1;" | ./sqldb
./sqldb my.db < script.sql
make test                    # == python3 -m unittest discover -s tests -t .
```

## Shell behaviour
* default list mode (`|` separator, NULL as empty, no headers); `.headers on|off`, `.mode list|csv|line|column|tabs`
  (also table, box, markdown, json, insert, quote), `.separator COL [ROW]`, `.nullvalue TEXT`, `.tables`, `.schema [T]`,
  `.read`, `.print`, `.dump`, `.bail`, `.echo`, `.quit`.
* Reals print like SQLite: `3.0`, `1.0e+20`, `Inf`; 15 significant digits, and integral doubles that
  do not round-trip print with 17 digits (`9.2233720368547758e+18`).
* Errors go to stderr as `Parse error near line N: msg` (syntax / name resolution) or
  `Error near line N: msg` (runtime, e.g. constraints); the rest of that input chunk is skipped like sqlite3
  does, processing continues with the next statement, and the exit status is 1 if any error occurred.
* Double-quoted tokens are always identifiers.

## Design
* `dbengine/tokenizer.py` — regex tokenizer. `dbengine/parser.py` — recursive-descent / precedence-climbing parser
  producing tuple ASTs (expressions) and dict ASTs (statements).
* `dbengine/values.py` — storage classes (None/int/float/str/bytes), affinity, comparison & collations
  (BINARY/NOCASE/RTRIM), arithmetic with int64 overflow to REAL, CAST, real formatting.
* `dbengine/functions.py` — scalar functions, printf, LIKE/GLOB, aggregates.
* `dbengine/query.py` — query execution. Expressions are compiled once to Python closures over a flat row
  (the columns of all FROM sources, each followed by a rowid slot). A SELECT is compiled to a plan:
  FROM (left-deep join pipeline of generators; equality conjuncts of ON/WHERE are served by a
  unique/secondary index, rowid lookup, or a transient hash index; WHERE conjuncts are pushed down to the
  earliest join level), then grouping/aggregation (groups come out in key order), DISTINCT, ORDER BY
  (stable multi-key sort with collations and NULLS FIRST/LAST), LIMIT/OFFSET. Sub-queries are compiled
  with an outer-row stack for correlation and cached when uncorrelated. Compound selects, VALUES and
  (recursive) CTEs are plan nodes too.
* `dbengine/catalog.py` — tables (rowid → row list; the rowid is the last slot of each row), hash indexes
  (also backing UNIQUE/PRIMARY KEY), views, and an undo log used for statement atomicity and transactions.
* `dbengine/executor.py` — statements: DDL, INSERT (conflict clauses, upsert, RETURNING), UPDATE, DELETE,
  BEGIN/COMMIT/ROLLBACK/SAVEPOINT, PRAGMA.
* `dbengine/shell.py` — statement splitting (`;` outside strings/comments/trigger bodies), dot-commands,
  output modes, error reporting.

## Window functions
`dbengine/windows.py`: rows are partitioned and sorted per OVER spec (named windows and `WINDOW` clauses are
resolved/merged); `row_number, rank, dense_rank, percent_rank, cume_dist, ntile, lag, lead, first_value,
last_value, nth_value` and any aggregate (with `FILTER`) are evaluated over ROWS / GROUPS / RANGE frames with
`EXCLUDE` options. Running frames starting at the partition start are computed incrementally. Windows are
evaluated after grouping, so `rank() over (order by sum(x))` works.

## Storage format (single file)
```
magic   8 bytes  "DB1000\x01\n"
frame*  type:u8 | length:u32le | crc32(payload):u32le | payload
```
* **SNAPSHOT (type 1)** — always the first frame: user_version, next root page number, every schema object in
  creation order (kind, stored `CREATE` SQL text, rootpage, auto-index rootpages) followed by every table's rows
  (`name, AUTOINCREMENT high-water mark, row count, rows`). Row = zig-zag varint rowid + one tagged value per column
  (`0` NULL, `1` INTEGER zig-zag varint, `2` REAL IEEE-754 double, `3` TEXT varint length + UTF-8, `4` BLOB varint length + bytes).
  On open the schema SQL is re-executed (rebuilding indexes, views, triggers) and rows are loaded.
* **DELTA (type 2)** — appended by each COMMIT: the user_version plus the *net* effect of the transaction
  (`put table rowid values` / `delete table rowid` / `seq table n`), derived from the undo log.
* A schema change (or a log larger than max(1 MiB, 2x snapshot)) rewrites the file as a new snapshot with
  write-to-temp + fsync + atomic `rename` + directory fsync, so a crash never leaves a half-written database.
  A crash while appending leaves a torn frame; on open any frame with a short length or bad CRC (and everything
  after it) is dropped and the file truncated to the last good frame, i.e. the interrupted transaction vanishes
  atomically. Deltas are flushed on every commit and fsync'ed at most every 50 ms and always at close (documented
  trade-off to keep large autocommit scripts fast). A missing file is created on the first write only.

## Transactions
All changes go through `Table.insert_row/update_row/delete_row`, which append to an undo log. A statement
remembers the log position and rolls back to it on error (statement atomicity, also inside transactions);
`BEGIN`/`SAVEPOINT` keep the log, `ROLLBACK [TO]` unwinds it, `COMMIT` hands the net change to the store.
`INSERT OR ROLLBACK` / `RAISE(ROLLBACK)` abort the whole transaction.

## DDL, triggers
`ALTER TABLE` RENAME TO / RENAME COLUMN / ADD COLUMN / DROP COLUMN rewrite the stored CREATE text (token based,
identifiers are re-quoted like SQLite) and rebuild the table, its indexes and dependent triggers/views from it.
Triggers (BEFORE/AFTER/INSTEAD OF, `UPDATE OF`, `WHEN`, `RAISE(...)`, `NEW`/`OLD`) run per row; a trigger does not
re-fire itself (recursive_triggers off). DML on a view works through INSTEAD OF triggers. Upsert supports several
`ON CONFLICT` clauses, `excluded.*`, and `WHERE` on the update.

## Assumptions / limitations
* `sqlite_sequence` is not exposed as a table (AUTOINCREMENT is honoured internally and persisted).
* Foreign keys are parsed but not enforced; generated columns are stored. JSON functions are not provided.
* One process at a time should open a database file (no locking).

## Status
M1 core, M2 relational features and M3 persistence/transactions/ALTER/triggers/upsert are implemented;
`make test` runs the complete suite.
