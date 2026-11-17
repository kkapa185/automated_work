# Benchmark report — tastejs/todomvc

**Ticket:** [`task.md`](task.md) (FE-12). It asks for a vanilla-JS TodoMVC app with the standard markup,
`localStorage` persistence and hash routing. The workspace received the official `app-spec.md` only.

**Reference execution:** the official Cypress suite, ported to Playwright with the same 30 test names
plus an extra check that empty items are not added ([`e2e.js`](e2e.js)). The same script runs against
the repo's `examples/javascript-es6` build for comparison.
- That example turned out to be *non-conforming*: it renders newest-first (`data.reverse()`), keeps todos
  in memory only, and drives toggle-all through its label. It fails 16 of 30 tests.
- With its ordering patched in a scratch copy, it passes 29 of 30. That validated the port; the
  remaining failure is the example's genuine lack of persistence.

## Result (attempt 1): score 1.00 (31/31)
The generated app passes every behaviour: adding, trimming, editing (save on Enter or blur, cancel on
Escape, delete on empty), toggle-all state, the counter, clear-completed, persistence across reload, the
three filters, highlighting of the active filter, and the browser back button. Its CSS is vendored, as
the ticket required.

**Process:** 4 turns on one session. $0.48, 5 min.
