# ChessEngine7 — a UCI chess engine (C++17)

A from-scratch chess engine speaking the Universal Chess Interface on stdin/stdout. No chess libraries,
no external engine code or tablebases.

## Build / run / test
```
./engine                 # builds build/engine with make on first use (needs g++ and make), then runs it
make                     # explicit build
./run_tests.sh           # build + full test-suite (python3 stdlib unittest only; no pip dependencies)
./smoke.sh               # quick end-to-end check
```
Example session:
```
$ printf 'position startpos moves e2e4\ngo depth 6\n' | ./engine
$ printf 'position startpos\ngo perft 4\n' | ./engine
```

## Supported UCI
`uci`, `isready`, `ucinewgame`, `setoption name Hash value <MB>` (1–4096, default 64),
`position startpos|fen <FEN> [moves ...]` (long algebraic, `e7e8q`, castling as `e1g1`),
`go depth N | movetime MS | wtime/btime/winc/binc/movestogo | nodes N | infinite`, `stop`, `quit`,
and `go perft N` (Stockfish format: `<move>: <count>`, blank line, `Nodes searched: N`).
During search it prints `info depth .. seldepth .. score cp|mate .. nodes .. nps .. time .. pv ..` and finally
`bestmove <move>` (`bestmove 0000` if there is no legal move). Search runs in a worker thread, so `stop` and
`isready` stay responsive. `go infinite` only reports `bestmove` after `stop`.
Extras: `d` prints the board, `Fen: ...`, `Key:` and `Checkers:`; `eval` prints the static evaluation.
Unknown commands are ignored; invalid FENs / illegal moves print an `info string` and leave the position unchanged.

## Design (src/)
* `chess.h/.cpp` — bitboards (classical ray attacks for sliders, lookup tables for leapers), `Position` with
  make/unmake, incremental Zobrist key, FEN I/O, pseudo-legal generation filtered by a king-safety test after
  each move (castling checked for out-of/through/into check; en passant incl. horizontal pins fall out of the
  post-move test), repetition / fifty-move / insufficient-material detection, perft.
* `eval.cpp` — tapered material + piece-square tables (generated from formulas), mobility, pawn-shield king
  safety and king-zone attack pressure, doubled/isolated/passed pawns, bishop pair, rook on open files, tempo.
* `search.cpp` — iterative deepening with aspiration windows, PVS negamax, quiescence search, transposition
  table (mate scores ply-adjusted), TT move / MVV-LVA / killers / history ordering, null-move pruning,
  reverse futility, late-move reductions and pruning, check extensions, mate-distance pruning,
  draws by repetition (twofold inside the search tree, threefold with game history), 50 moves, material.
  Time management: `movetime` hard limit (minus a small margin); clocks use time/movestogo (default 30) + 3/4 inc.
* `main.cpp` — the UCI loop. `output.h` — thread-safe flushed output.

## Tests (tests/, R-numbers refer to `.orchestrator/requirements.md`)
* `test_perft.py` — R4–R6: published perft values (start d1-5, Kiwipete d1-4, positions 3–6 incl. mirrored 4), output
  format, divide, Kiwipete depth-4 time bound (< 60 s; takes ~0.2 s).
* `test_fen.py` — R3/R11: round trips, moves updating FEN/castling rights/ep/promotion, invalid FEN robustness.
* `test_special.py` — R4/R12: castling rules, en passant (incl. pin), promotions, pins, check evasion, mate,
  stalemate, fifty-move, threefold-repetition and insufficient-material draws.
* `test_uci.py` — R1/R2/R7: handshake, info format, movetime/clock/nodes limits, infinite+stop, quit, EOF handling.
* `test_consistency.py` — R3/R8/R9: incremental Zobrist key equals key recomputed from FEN, transpositions share a key, evaluation is colour-symmetric.
* `test_play.py` — R8/R10: mate in 1/2 (incl. smothered mate), and full games against a random mover.

## Notes / assumptions
Castling uses standard UCI king-two-squares notation (no Chess960). `go` without limits is treated as infinite.
After a bounded `go`, closing stdin lets the search finish and print `bestmove` before exiting.
