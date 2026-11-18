# DB-1000 requirements

## Product
DB-1000 is an embeddable SQL database engine written from scratch in Python 3 (stdlib only; the `sqlite3`
module and any DB/SQL-parser library are forbidden) plus a shell `./sqldb [DATABASE_FILE]` that reads SQL
statements and dot-commands from stdin and behaves like the `sqlite3` shell fed a script. SQL dialect and
semantics follow SQLite. Persistent storage is a single file in a custom format (journaled snapshot of
pages/records); in-memory when no path is given.

## Acceptance criteria
Storage & transactions
- R1  `./sqldb FILE` persists committed data; reopening shows it. No file => in-memory DB.
- R2  BEGIN [DEFERRED|IMMEDIATE|EXCLUSIVE] [TRANSACTION], COMMIT/END [TRANSACTION], ROLLBACK atomically undo all
      changes (data and schema). Errors inside a transaction leave it open. Nested BEGIN / COMMIT without BEGIN are errors.
- R3  SAVEPOINT / RELEASE / ROLLBACK [TRANSACTION] TO [SAVEPOINT] work, nested, and start a transaction if none open.
- R4  Every statement outside a transaction is atomic (e.g. multi-row INSERT failing on row 3 inserts nothing; UPDATE failing a constraint midway changes nothing).
- R5  A crash/kill mid-write never corrupts the file (write temp + fsync + atomic rename); file is rewritten only on commit.
DDL
- R6  CREATE TABLE [IF NOT EXISTS] with types/affinity rules (INT, TEXT, REAL, NUMERIC, BLOB, none), PRIMARY KEY (column and table
      constraint, composite, AUTOINCREMENT accepted), INTEGER PRIMARY KEY = rowid alias, NOT NULL, UNIQUE, CHECK, DEFAULT (literal, expr in parens, CURRENT_TIMESTAMP etc.), COLLATE, table constraints, CREATE TABLE AS SELECT, WITHOUT ROWID accepted, FOREIGN KEY clauses parsed (not enforced).
- R7  CREATE [UNIQUE] INDEX [IF NOT EXISTS], CREATE VIEW [IF NOT EXISTS], DROP TABLE/INDEX/VIEW [IF EXISTS].
- R8  ALTER TABLE ADD COLUMN, RENAME TO, RENAME COLUMN [TO] (also DROP COLUMN best effort).
- R9  `sqlite_schema` / `sqlite_master` queryable (type,name,tbl_name,rootpage,sql) with SQLite-style normalized sql text for tables/indexes/views.
DML
- R10 INSERT [OR IGNORE|REPLACE|ABORT|FAIL|ROLLBACK] / REPLACE INTO ... VALUES (multi-row), SELECT, DEFAULT VALUES, column lists, RETURNING.
- R11 Upsert ON CONFLICT [(cols)] DO NOTHING | DO UPDATE SET ... [WHERE], `excluded.` references.
- R12 UPDATE [OR ...] ... [FROM] [WHERE], DELETE ... [WHERE]; rowid / oid / _rowid_; last_insert_rowid(), changes(), total_changes().
- R13 Constraint errors with SQLite messages: `UNIQUE constraint failed: t.c`, `NOT NULL constraint failed: t.c`, `CHECK constraint failed: name/expr`, `datatype mismatch`.
Queries
- R14 SELECT with DISTINCT, expressions & aliases, `*`/`t.*`, WHERE, GROUP BY/HAVING (aliases/ordinals), bare columns with min/max.
- R15 Joins: [INNER] JOIN, LEFT [OUTER], RIGHT/FULL [OUTER], CROSS, NATURAL, USING, comma joins, ON.
- R16 Subqueries: scalar, IN (subquery/list), EXISTS/NOT EXISTS, correlated, in FROM, row values.
- R17 ORDER BY expressions, ordinals, aliases, ASC/DESC, NULLS FIRST/LAST, COLLATE BINARY/NOCASE/RTRIM; LIMIT/OFFSET and `LIMIT a, b`.
- R18 Compound UNION [ALL]/INTERSECT/EXCEPT with ORDER BY/LIMIT; VALUES as a select.
- R19 WITH [RECURSIVE] CTEs (incl. column lists, multiple CTEs, recursive with UNION/UNION ALL, LIMIT termination).
- R20 Window functions: row_number, rank, dense_rank, percent_rank, cume_dist, ntile, lag, lead, first_value, last_value, nth_value, and aggregates OVER (PARTITION BY, ORDER BY, ROWS/RANGE/GROUPS frames, EXCLUDE optional), named WINDOW.
Expressions & types
- R21 Dynamic typing: storage classes, typeof, affinity application on insert/compare, integer overflow -> real, integer division truncation, `%`, `/` by zero -> NULL, bit ops, unary ops.
- R22 Comparison across classes (NULL<INTEGER/REAL<TEXT<BLOB), collations, three-valued logic AND/OR/NOT, IS [NOT] [DISTINCT FROM], CASE, CAST, BETWEEN, IN, LIKE/GLOB/ESCAPE, ||, blobs x'..', hex literals 0x.., NOT NULL/ISNULL/NOTNULL.
- R23 Scalar functions: abs, char, coalesce, format/printf, hex, ifnull, iif, instr, length, like, lower, ltrim, max, min (multi-arg), nullif, quote, replace, round, rtrim, sign, substr/substring, trim, typeof, unicode, upper, random, randomblob, zeroblob, glob, unhex, likelihood, lower/upper, last_insert_rowid, changes, total_changes, sqlite_version, date/time basics (date, time, datetime, julianday, strftime) best effort.
- R24 Aggregates: avg, count(*/expr/DISTINCT), group_concat/string_agg (with separator, DISTINCT), max, min, sum (int overflow error, total, NULL on empty), total.
- R25 Double-quoted tokens are always identifiers (error `no such column: "x"` style if unresolved, never a string); single-quoted are strings.
Shell
- R26 List mode default: `|` separator, NULL empty, no headers. Reals: `3.0`, `1.0e+20`, `9.2233720368547758e+18`, `Inf`, `-Inf`, `NaN`→NULL-like empty; 15 significant digits formatting like SQLite (`%!.15g`).
- R27 Dot-commands: .headers on|off, .mode list|csv|line|column|tabs (also box/table/json/insert best effort), .separator COL [ROW], .nullvalue TEXT, .tables, .schema [TABLE], .quit/.exit, .help-free ignore of unknown with error `unknown command or invalid arguments:  "x". Enter ".help" for help`; also .bail, .echo, .read, .width, .timer, .show best effort.
- R28 Statement splitting on `;` respecting strings, comments (`--`, `/* */`), identifiers in quotes/brackets/backticks, and CREATE TRIGGER bodies; final statement without `;` is executed at EOF.
- R29 Errors: stderr `Parse error near line N: <msg>` for syntax errors, `Error near line N: <msg>` for runtime errors (line = line where statement starts); statement skipped, continue; exit status 1 if any error else 0. Common messages: `no such table: x`, `no such column: x`, `table x already exists`, `near "x": syntax error`.
- R30 CSV mode quoting per RFC4180 (fields containing `,` `"` newline quoted); line mode `col = value` blocks separated by blank line; column mode with headers/width auto; tabs mode.
Deliverables
- R31 Test-suite (`tests/`, run with `python3 -m unittest discover tests` / `make test`), README documenting storage format and query execution; `sqldb` executable script at repo root.
- R32 Triggers (CREATE TRIGGER BEFORE/AFTER INSERT/UPDATE/DELETE) best effort, PRAGMAs table_info/foreign_keys etc. best effort (ignored otherwise).

## Assumptions
- Language Python 3.13, stdlib only; performance targets modest (10^5 rows interactive).
- Persistence: whole-database snapshot serialized to a single file on commit (atomic rename); documented in README. Indexes are in-memory structures rebuilt on load (UNIQUE enforcement uses them).
- Error message texts follow SQLite where known; otherwise a sensible message.
- Real number formatting uses `%.15g` plus ".0" when integral, exponent form `1.0e+20` (SQLite style); 9.2233720368547758e+18 is printed by 17-digit fallback used by SQLite when 15 digits don't round trip? Assumption: SQLite prints with 15 sig digits, but ticket example shows 17 digits for 2^63 — implement shortest repr that round-trips if %.15g does not round-trip (%.17g style), matching examples.
- Random/time functions are non-deterministic; tested by type/range only.

## Test strategy
- Unit tests (unittest) for tokenizer/parser, value/affinity/comparison, formatter (known answers from SQLite docs semantics).
- Script-level tests: feed SQL scripts to `./sqldb` via subprocess, assert exact stdout/stderr/exit status (R1-R30), including every ticket example.
- Persistence tests: reopen file, rollback, savepoints, crash-simulation (partial temp file ignored).
- Error-path tests for R29.

## Additional assumptions (review)
- Per the ticket ("skip that statement and continue with the next"), when one line holds several statements and
  one fails, the failing statement is skipped and the following statements still run (after a syntax error the
  parser resynchronises at the next `;`).
- CSV mode terminates rows with CRLF; headers are printed only together with the first result row.
- `sqlite_sequence` is not exposed; AUTOINCREMENT is honoured and persisted internally.
