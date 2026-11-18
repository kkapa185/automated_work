"""Shared helpers: drive ./engine over UCI."""
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "engine")
STARTPOS = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def run(commands, timeout=120):
    """Send commands (list of str), close stdin, return stdout lines."""
    p = subprocess.run([ENGINE], input="\n".join(commands) + "\n", capture_output=True, text=True, timeout=timeout)
    return p.stdout.splitlines()


def perft(fen, depth, timeout=300):
    pos = "position startpos" if fen is None else "position fen " + fen
    lines = run([pos, "go perft %d" % depth, "quit"], timeout)
    total = [l for l in lines if l.startswith("Nodes searched:")][0]
    return int(total.split(":")[1]), lines


def divide(fen, depth=1):
    _, lines = perft(fen, depth)
    res = {}
    for l in lines:
        if ": " in l and not l.startswith("Nodes") and not l.startswith("info"):
            m, c = l.split(": ")
            res[m] = int(c)
    return res


def legal_moves(position_cmd):
    lines = run([position_cmd, "go perft 1", "quit"])
    return [l.split(":")[0] for l in lines if ": " in l and not l.startswith("Nodes")]


def fen_of(position_cmd):
    lines = run([position_cmd, "d", "quit"])
    return [l for l in lines if l.startswith("Fen: ")][0][5:]


def bestmove(position_cmd, go="go depth 5", timeout=60):
    lines = run([position_cmd, go], timeout)
    bm = [l for l in lines if l.startswith("bestmove")]
    return bm[0].split()[1], lines


class Engine:
    """Interactive engine process for stop/timing tests."""

    def __init__(self):
        self.p = subprocess.Popen([ENGINE], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def send(self, s):
        self.p.stdin.write(s + "\n")
        self.p.stdin.flush()

    def read_until(self, prefix, timeout=30):
        t0 = time.time()
        lines = []
        while time.time() - t0 < timeout:
            l = self.p.stdout.readline()
            if not l:
                break
            l = l.rstrip("\n")
            lines.append(l)
            if l.startswith(prefix):
                return lines
        raise AssertionError("timeout waiting for %r, got %r" % (prefix, lines[-5:]))

    def close(self):
        try:
            self.send("quit")
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()
