# Benchmark report — official-stockfish/Stockfish

**Ticket:** [`task.md`](task.md) (GAME-ENGINE-7). It asks for a UCI chess engine with exact legal move
generation, a `go perft` command, iterative-deepening alpha-beta with quiescence and a transposition table,
and an evaluation function. No chess libraries were allowed.

**Reference execution:** Stockfish built from the repo; its NNUE network was fetched from GitHub's LFS host.
The hidden harness [`compare.py`](compare.py) runs:
- `go perft` on 8 standard positions: start, Kiwipete, positions 3–6, an en-passant pin and promotions.
  Totals **and** per-move divide counts must match Stockfish exactly;
- Kiwipete at depth 4 (4,085,603 nodes) under 60 s;
- UCI conformance: `uci/uciok`, `isready`, `go movetime`, `go infinite` + `stop`;
- four mate-in-one positions, checked with Stockfish's move list and `Checkers:`;
- capturing a hanging queen;
- 4 games against a random mover, with every move validated as legal by Stockfish.

## Result (attempt 2): **score 1.00 (28/28)**
- Every perft total and divide count matches Stockfish.
- Kiwipete at depth 4 runs in 0.1 s.
- All mates are found, every UCI check passes, and it won **4/4** games with only legal moves.

**Attempt history:**
- Attempt 1 was cancelled because of a system bug it exposed. The 5-hour usage limit hit during the
  *plan* turn, after the session had been created. On resume the orchestrator saw a session id and
  skipped hydration and planning, going straight to implementation.
- Fix: planning completion is now decided from the turn history, and an interrupted plan turn is re-sent to
  the same session. Regression test: `test_interrupted_first_turn_with_bound_session_still_plans`.

**Process (attempt 2):** 5 turns on one session. $1.67.

**Harness fixes:**
- The UCI reader originally used `select()` with buffered `readline()`, which stalls. It now uses a reader
  thread.
- Two of my test positions were illegal (the side not to move was in check), and Stockfish rejects
  illegal positions. Both were replaced.
