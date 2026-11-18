# Benchmark report — kanaka/mal (Make-A-Lisp)

**Ticket:** [`task.md`](task.md) (LANG-88). It asks for all 11 mal steps (REPL → self-hosting) in a language of
the system's choice, using the standard `STEP=... ./run` convention. The mal process guide and per-step
pseudocode were provided as the normative input.

**Reference execution:** the official mal test-suite, the repo's `runtest.py` with `impls/tests/step*.mal`:
1,334 tests over 11 steps. It runs against the generated interpreter mounted at `impls/<impl>/`, as the
suite expects. Then comes the self-hosting check: the repo's **mal implementation written in mal**
(`impls/mal`) is run *on top of* the generated stepA and must pass steps 2, 4 and 9.

## Result (attempt 1): **score 1.00 — 1,334/1,334 tests**
- All 11 steps pass, optional and deferrable tests included.
- The self-hosted mal-in-mal passes 387/387 tests.

**Process:** milestone mode with 4 milestones (skeleton + steps 0–3 → functions/TCO/files → quasiquote,
macros, try → self-hosting/hardening). 8 turns on one session. $3.88.

**Harness fixes (no rerun needed):**
- The suite reads `../tests/*.mal` relative to the implementation directory. The first harness ran from
  the workspace root, so step 6's file tests looked like failures (first score 0.88).
- The harness now copies the app into an `impls/` layout. Copying is required: `..` from a symlinked
  directory resolves to the physical parent, so a symlink does not work.
