# GAME-ENGINE-7: A UCI chess engine

Write a chess engine (any language; no chess libraries for move generation or search such as
python-chess, chess.js, Stockfish/other engine code or tablebases) that speaks the Universal Chess
Interface over stdin/stdout, runnable as `./engine` from the workspace root.

* Rules: complete and exact legal move generation — castling rights and through-check rules, en passant
  (incl. pins), promotions to all four pieces, check/checkmate/stalemate, fifty-move and threefold
  repetition draws in search. Move generation must be exact: `perft` node counts must equal the
  published values for the standard test positions (start position, "Kiwipete", and the other
  chessprogramming.org perft positions) — and be fast enough to compute perft depth 4 of Kiwipete
  (4,085,603 nodes) in under a minute.
* UCI: `uci` (prints `id name ...`, `id author ...`, options, `uciok`), `isready` → `readyok`,
  `ucinewgame`, `position startpos|fen <FEN> [moves <m1> ...]` (long algebraic, e.g. `e7e8q`),
  `go` with `depth N`, `movetime MS`, `wtime/btime/winc/binc/movestogo`, `nodes`, `infinite` + `stop`,
  `quit`. During search print `info depth .. score cp|mate .. nodes .. nps .. pv ..` lines and end with
  `bestmove <move>`. Must respond within the given movetime (+ small overhead).
* `go perft N` prints one line per legal root move `<move>: <count>`, a blank line, and
  `Nodes searched: <total>` (same format as Stockfish).
* Search: iterative deepening alpha-beta (PVS/negamax) with quiescence search, move ordering
  (TT move, MVV-LVA, killers, history), transposition table with Zobrist hashing, and a sensible
  evaluation (material, piece-square tables, mobility, king safety, pawn structure). It must find
  forced mates in one and win easily against a random mover.

Deliverables: the engine, a test-suite (perft suite, FEN round-trips, special moves, UCI protocol), README.
