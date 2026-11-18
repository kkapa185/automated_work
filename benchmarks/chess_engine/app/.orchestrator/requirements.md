# Requirements: GAME-ENGINE-7 UCI chess engine

## Product
A from-scratch UCI chess engine in C++17 (no chess libraries), launched as `./engine` (a small launcher script
that builds the binary with `make` on first use, then execs it). It has exact legal move generation (bitboards,
magic-free sliding attacks via classical ray/hyperbola-quintessence), Zobrist hashing, a PVS alpha-beta search with
quiescence, TT, move ordering, and a hand-crafted evaluation. Tests are in Python (pytest-free, `unittest`) driving the binary.

## Acceptance criteria
R1. `./engine` runs from workspace root, reads UCI on stdin, writes to stdout (flushed); exits on `quit`/EOF.
R2. `uci` prints `id name`, `id author`, `option name Hash type spin ...`, then `uciok`. `isready` -> `readyok`. `ucinewgame` clears TT.
R3. `position startpos|fen <FEN> [moves ...]` incl. long algebraic with promotions (`e7e8q`), castling as king-two-squares (`e1g1`), en passant.
R4. Legal move generation exact: castling rights, no castling through/out of/into check, en passant incl. horizontal pins, promotions to N/B/R/Q, check/mate/stalemate.
R5. `go perft N` prints `<move>: <count>` per root move, blank line, `Nodes searched: <total>`. Values equal published perft for: startpos (d1-5: 20,400,8902,197281,4865609), Kiwipete (48,2039,97862,4085603), pos3 (14,191,2812,43238,674624), pos4 (6,264,9467,422333), pos4 mirrored, pos5 (44,1486,62379,2103487), pos6 (46,2079,89890,3894594).
R6. Kiwipete perft 4 completes in < 60 s (target < 2 s).
R7. `go depth N`, `movetime MS`, `wtime/btime/winc/binc/movestogo`, `nodes N`, `infinite` + `stop`, `ponder`/other tokens ignored gracefully. Emits `info depth .. score cp|mate .. nodes .. nps .. time .. pv ..` and ends with `bestmove <move>` (`bestmove 0000` if no legal moves). Respects movetime within small overhead; search runs in a thread so `stop`/`isready` stay responsive.
R8. Search: iterative deepening, PVS negamax, quiescence, TT w/ Zobrist, TT move/MVV-LVA/killers/history ordering, null move, LMR, check extension; mate scores reported as `score mate N` (moves, negative when being mated); fifty-move and threefold (twofold within search) repetition draws.
R9. Evaluation: material, piece-square tables (tapered), mobility, king safety (pawn shield), pawn structure (doubled/isolated/passed), bishop pair; symmetric.
R10. Finds forced mate in one (and mate in 2/3 tests); wins easily versus a random mover.
R11. FEN parse/serialize round-trip (exposed via non-standard `d`/`fen` debug command printing `Fen: ...`); invalid FEN does not crash.
R12. Draw detection: fifty-move rule, repetition, insufficient material (K v K, K+minor v K).
R13. Deliverables: engine, tests (perft suite, FEN round-trips, special moves, UCI protocol, mate/random-mover play, perf), README, Makefile.

## Assumptions
- Position after `go` with no limits = infinite until stop. Hash option default 64 MB; Threads option accepted (ignored).
- Castling in UCI is e1g1 style (not Chess960).
- Debug commands `d` (prints board + `Fen:`) and `eval` are extensions.
- Mate-in-1 default depth if `go` has no params: infinite.

## Test strategy
- tests/test_perft.py: R4,R5,R6 with published numbers (from chessprogramming.org, hardcoded from the written tables).
- tests/test_fen.py: R3,R11. tests/test_special.py: R4 special moves/draws. tests/test_uci.py: R1,R2,R7,R8.
- tests/test_play.py: R10 (mate in 1/2, vs random mover using a tiny independent move source = the engine's perft listing).

- Test-suite uses only the Python standard library (no pip deps); `go` after stdin EOF completes bounded searches.
- When `movetime`/clock is used the search may stop after an iteration once half the soft budget is spent.
