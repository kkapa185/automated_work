"""Perft divide counts vs Stockfish, UCI conformance, mate-finding and games against a random mover."""
import argparse
import random
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish  # noqa: E402

PERFT = [
    ("startpos", "startpos", 4),
    ("kiwipete", "fen r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 3),
    ("position3", "fen 8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4),
    ("position4", "fen r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3),
    ("position5", "fen rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 3),
    ("position6", "fen r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", 3),
    ("ep-pin", "fen 8/8/8/KPp4r/8/8/8/7k w - c6 0 2", 3),
    ("promos", "fen n1n5/PPPk4/8/8/8/8/4Kppp/5N1N b - - 0 1", 3),
]
MATES = ["fen 6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "fen k7/8/1K6/8/8/8/8/7R w - - 0 1",
         "fen r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 0 1",
         "fen K7/8/1k6/8/8/8/8/7r b - - 0 1"]


class Engine:
    """UCI process wrapper. A reader thread feeds a queue (select() + buffered readline can stall)."""

    def __init__(self, argv, cwd=None):
        import queue
        import threading
        self.p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.q = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.p.stdout:
            self.q.put(line.rstrip("\n"))
        self.q.put(None)

    def send(self, line):
        try:
            self.p.stdin.write(line + "\n")
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def until(self, pred, timeout):
        import queue
        lines, deadline = [], time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                return lines, False
            try:
                line = self.q.get(timeout=left)
            except queue.Empty:
                return lines, False
            if line is None:
                return lines, False
            lines.append(line)
            if pred(line):
                return lines, True

    def close(self):
        try:
            self.send("quit")
            self.p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.p.kill()


def perft(e, pos, depth, timeout):
    e.send(f"position {pos}")
    t0 = time.time()
    e.send(f"go perft {depth}")
    lines, ok = e.until(lambda l: l.startswith("Nodes searched"), timeout)
    divide = {m: int(c) for m, c in (re.match(r"^(\w+): (\d+)$", l).groups() for l in lines if re.match(r"^\w+: \d+$", l))}
    total = next((int(l.split(":")[1]) for l in lines if l.startswith("Nodes searched")), None)
    return divide, total, time.time() - t0


def legal_moves(sf, pos):
    d, _, _ = perft(sf, pos, 1, 10)
    return set(d)


def in_check(sf, pos):
    sf.send(f"position {pos}")
    sf.send("d")
    lines, _ = sf.until(lambda l: l.startswith("Checkers:"), 10)
    return bool(lines and lines[-1].split(":", 1)[1].strip())


def with_moves(pos, moves):
    return pos + (" moves " + " ".join(moves) if moves else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app).resolve(), Path(a.reference)
    sf = Engine([str(ref / "src" / "stockfish")])
    checks = []
    try:
        eng = Engine([str(app / "engine")], cwd=str(app))
    except OSError as exc:
        checks.append(check("engine starts", False, repr(exc)))
        return finish(a.out, checks)
    eng.send("uci")
    lines, ok = eng.until(lambda l: l.strip() == "uciok", 10)
    checks.append(check("uci -> id name ... uciok", ok and any(l.startswith("id name") for l in lines), lines[:3]))
    eng.send("isready")
    _, ok = eng.until(lambda l: l.strip() == "readyok", 10)
    checks.append(check("isready -> readyok", ok))
    for name, pos, depth in PERFT:
        rd, rt, _ = perft(sf, pos, depth, 120)
        gd, gt, dt = perft(eng, pos, depth, 180)
        checks.append(check(f"perft {name} depth {depth}: total {rt} nodes", gt == rt, f"got {gt} in {dt:.1f}s"))
        bad = {m: (gd.get(m), rd.get(m)) for m in set(rd) | set(gd) if gd.get(m) != rd.get(m)}
        checks.append(check(f"perft {name} depth {depth}: divide identical", not bad, str(dict(list(bad.items())[:5]))))
    rd, rt, _ = perft(sf, PERFT[1][1], 4, 300)
    _, gt, dt = perft(eng, PERFT[1][1], 4, 120)
    checks.append(check("perft kiwipete depth 4 (4,085,603) correct in < 60 s", gt == rt and dt < 60, f"{gt} in {dt:.1f}s"))
    # mate in one
    for pos in MATES:
        eng.send("ucinewgame"); eng.send(f"position {pos}"); eng.send("go depth 4")
        lines, ok = eng.until(lambda l: l.startswith("bestmove"), 30)
        bm = lines[-1].split()[1] if ok and len(lines[-1].split()) > 1 else None
        after = with_moves(pos, [bm]) if bm else None
        mated = bm in legal_moves(sf, pos) and not legal_moves(sf, after) and in_check(sf, after) if bm else False
        checks.append(check(f"finds mate in one: {pos[4:40]}...", mated, f"bestmove {bm}"))
    # movetime respected and info lines
    eng.send("position startpos moves e2e4 e7e5 g1f3"); t0 = time.time(); eng.send("go movetime 500")
    lines, ok = eng.until(lambda l: l.startswith("bestmove"), 10)
    dt = time.time() - t0
    checks.append(check("go movetime 500 answers within 1.5 s with a legal move and info lines", ok and dt < 1.5 and any(l.startswith("info") and " pv " in l for l in lines)
                        and lines[-1].split()[1] in legal_moves(sf, "startpos moves e2e4 e7e5 g1f3"), f"{dt:.2f}s"))
    eng.send("position startpos"); eng.send("go infinite"); time.sleep(0.5); eng.send("stop")
    _, ok = eng.until(lambda l: l.startswith("bestmove"), 5)
    checks.append(check("go infinite + stop -> bestmove", ok))
    # hanging piece must be captured
    pos = "fen rnb1kbnr/pppp1ppp/8/4q3/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 1"
    eng.send(f"position {pos}"); eng.send("go depth 5")
    lines, ok = eng.until(lambda l: l.startswith("bestmove"), 30)
    checks.append(check("captures a hanging queen (Nf3xe5)", ok and lines[-1].split()[1] == "f3e5", lines[-1:]))
    # games vs random mover
    rng = random.Random(11)
    results, illegal = [], 0
    for game in range(4):
        moves, eng_white = [], game % 2 == 0
        eng.send("ucinewgame")
        result = "draw"
        for ply in range(160):
            pos = with_moves("startpos", moves)
            legal = legal_moves(sf, pos)
            if not legal:
                result = ("loss" if ((ply % 2 == 0) == eng_white) else "win") if in_check(sf, pos) else "draw"
                break
            if (ply % 2 == 0) == eng_white:
                eng.send(f"position {pos}"); eng.send("go movetime 100")
                lines, ok = eng.until(lambda l: l.startswith("bestmove"), 10)
                mv = lines[-1].split()[1] if ok and len(lines[-1].split()) > 1 else None
                if mv not in legal:
                    illegal += 1
                    result = "illegal"
                    break
            else:
                mv = rng.choice(sorted(legal))
            moves.append(mv)
        results.append(result)
    checks.append(check("plays only legal moves in 4 games", illegal == 0, results))
    checks.append(check("beats a random mover in at least 3 of 4 games", results.count("win") >= 3, results))
    eng.close(); sf.close()
    finish(a.out, checks)


if __name__ == "__main__":
    main()
