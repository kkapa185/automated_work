# DB-1000: An embeddable SQL database engine with a `sqlite3`-compatible shell

Build a relational database engine from scratch (any language; no database libraries or engines —
not SQLite/libsqlite3, DuckDB, H2, apsw, or SQL parsers/planners such as sqlglot) and a command-line shell
`./sqldb [DATABASE_FILE]` that reads SQL statements and dot-commands from stdin, exactly like the
`sqlite3` shell does when fed a script. The SQL dialect and semantics are SQLite's (the SQLite SQL
documentation is the normative reference for behaviour):

* Storage: a single database file (any format of your own design) when a path is given — committed data
  must survive closing and reopening; in-memory when no file is given. Transactions (`BEGIN [DEFERRED|
  IMMEDIATE|EXCLUSIVE] [TRANSACTION]`, `COMMIT/END`, `ROLLBACK`, `SAVEPOINT`/`RELEASE`/`ROLLBACK TO`) with
  atomic rollback; each statement outside a transaction is atomic.
* DDL: `CREATE TABLE [IF NOT EXISTS]` with column types/affinity, `PRIMARY KEY` (incl. `INTEGER PRIMARY
  KEY` = rowid alias), `NOT NULL`, `UNIQUE`, `CHECK`, `DEFAULT`, table constraints; `CREATE [UNIQUE] INDEX`,
  `CREATE VIEW`, `DROP TABLE/INDEX/VIEW [IF EXISTS]`, `ALTER TABLE ... ADD COLUMN / RENAME TO / RENAME
  COLUMN`; the `sqlite_schema` (alias `sqlite_master`) table.
* DML: `INSERT [OR IGNORE|OR REPLACE] ... VALUES (multi-row) / SELECT / DEFAULT VALUES`, upsert
  (`ON CONFLICT ... DO NOTHING|DO UPDATE`), `UPDATE`, `DELETE`, `rowid`, `last_insert_rowid()`, `changes()`.
* Queries: full `SELECT` with `DISTINCT`, all join types (`[INNER] JOIN`, `LEFT [OUTER] JOIN`, `CROSS`,
  `NATURAL`, `USING`), subqueries (scalar, `IN`, `EXISTS`, correlated, in `FROM`), `GROUP BY/HAVING`,
  `ORDER BY` (expressions, ordinals, `ASC/DESC`, `NULLS FIRST/LAST`, collations BINARY/NOCASE),
  `LIMIT/OFFSET` (both syntaxes), compound `UNION [ALL]/INTERSECT/EXCEPT`, `WITH [RECURSIVE]` CTEs,
  window functions (`row_number, rank, dense_rank, lag, lead, first_value, last_value, ntile`, aggregates
  `OVER (PARTITION BY ... ORDER BY ... [frame])`).
* Expressions & types: SQLite's dynamic typing with type affinity, storage classes (`typeof`), numeric
  rules (integer overflow to real, integer division, `%`), comparison/collation rules across storage
  classes, three-valued NULL logic, `CASE`, `CAST`, `BETWEEN`, `IN`, `LIKE`/`GLOB`/`ESCAPE`, `||`, blobs
  `x'..'`. Core functions: `abs, char, coalesce, format/printf, hex, ifnull, iif, instr, length, like,
  lower, ltrim, max, min, nullif, quote, replace, round, rtrim, sign, substr/substring, trim, typeof,
  unicode, upper, random, zeroblob`; aggregates `avg, count, group_concat/string_agg, max, min, sum, total`.
* Shell behaviour identical to `sqlite3` reading a script from stdin: default list mode (columns
  separated by `|`, NULL as empty string, no headers); numbers printed like SQLite (reals always with a
  decimal point or exponent, e.g. `3.0`, `1.0e+20`, `9.2233720368547758e+18`, `Inf`); dot-commands
  `.headers on|off`, `.mode list|csv|line|column|tabs`, `.separator COL`, `.nullvalue TEXT`,
  `.tables`, `.schema [TABLE]`. On an error, print a message to stderr (e.g.
  `Parse error near line N: ...` / `Error near line N: ...`), skip that statement and continue with the
  next; exit status 1 if any error occurred, else 0. Double-quoted string literals are NOT accepted
  (a double-quoted token is always an identifier).

Deliverables: engine + shell, a test-suite, a README describing the storage format and query execution.
