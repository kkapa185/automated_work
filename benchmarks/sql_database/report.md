# Benchmark report — sqlite/sqlite

**Ticket:** [`task.md`](task.md) (DB-1000). It asks for a SQL database engine written from scratch, with a
`sqlite3`-compatible shell. It must have file persistence and transactions, plus joins, subqueries,
compound queries, CTEs, window functions, upserts, SQLite typing and affinity, and dot-commands.

**Reference execution:** the `sqlite3` shell built from the repo (3.5x). The hidden harness
[`compare.py`](compare.py) feeds both the same 10 scripts: about 120 statements, covering types and number
formatting, strings, joins, set operations, CTEs/windows, constraints/transactions/savepoints/upsert, DDL,
CLI modes and error recovery. It compares stdout byte for byte and the number of statement errors and the
exit code, then checks persistence across processes and runs a 20,000-row indexed workload.

## Result (attempt 1): score 0.91 (21/23)
- 8 of 10 scripts are byte-identical, including window functions, recursive CTEs, upsert, savepoints and
  `INSERT OR REPLACE`.
- Error counts match in all scripts. Persistence works, and so does the 20k-row workload.
- Two differences remain:
  1. `-0.0` prints as `-0.0`; SQLite prints `0.0`.
  2. CSV mode does not quote fields that contain a space; SQLite quotes `"x y"`.

**Process:** milestone mode, 6 turns on one session. $5.83.
