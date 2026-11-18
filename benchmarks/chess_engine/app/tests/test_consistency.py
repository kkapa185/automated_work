"""R3, R8, R9: incremental hashing consistency and evaluation symmetry."""
import unittest

from helpers import run, STARTPOS


def key_and_fen(cmd):
    lines = run([cmd, "d", "quit"])
    key = [l for l in lines if l.startswith("Key:")][0]
    fen = [l for l in lines if l.startswith("Fen: ")][0][5:]
    return key, fen


def evaluation(fen):
    lines = run(["position fen " + fen, "eval", "quit"])
    return int([l for l in lines if l.startswith("Eval:")][0].split()[1])


def mirror(fen):
    b, stm, cas, ep, hm, fm = fen.split()
    rows = [r.swapcase() for r in reversed(b.split("/"))]
    cas2 = "".join(sorted(cas.swapcase(), key=lambda c: "KQkq".index(c))) if cas != "-" else "-"
    ep2 = "-" if ep == "-" else ep[0] + str(9 - int(ep[1]))
    return "/".join(rows) + " " + ("b" if stm == "w" else "w") + " " + cas2 + " " + ep2 + " " + hm + " " + fm


SEQS = [
    "position startpos moves e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 e1g1 f8c5 d2d3 d7d6 c1g5 e8g8",
    "position startpos moves e2e4 d7d5 e4e5 f7f5 e5f6 e7e6 f6g7 f8e7 g7h8q",
    "position startpos moves a2a4 b7b5 a4b5 a7a6 b5a6 c8a6 b1c3 b8c6 e2e3 a8b8",
    "position fen r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1 moves a2a4 b4a3 e1c1 a3b2 c1b1 b2a1n",
]


class ConsistencyTests(unittest.TestCase):
    def test_incremental_key_equals_key_from_fen(self):
        for cmd in SEQS:
            with self.subTest(cmd=cmd):
                key, fen = key_and_fen(cmd)
                key2, fen2 = key_and_fen("position fen " + fen)
                self.assertEqual(key, key2)
                self.assertEqual(fen, fen2)

    def test_transposition_same_key(self):
        a = key_and_fen("position startpos moves g1f3 g8f6 b1c3 b8c6")[0]
        b = key_and_fen("position startpos moves b1c3 b8c6 g1f3 g8f6")[0]
        c = key_and_fen("position startpos moves g1f3 b8c6 b1c3 g8f6")[0]
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertNotEqual(a, key_and_fen("position startpos")[0])

    def test_side_to_move_changes_key(self):
        f = "4k3/8/8/8/8/8/8/4K3"
        self.assertNotEqual(key_and_fen("position fen %s w - - 0 1" % f)[0], key_and_fen("position fen %s b - - 0 1" % f)[0])

    def test_eval_color_symmetric(self):
        fens = [STARTPOS,
                "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
                "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
                "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
                "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"]
        for f in fens:
            with self.subTest(fen=f):
                self.assertEqual(evaluation(f), evaluation(mirror(f)))

    def test_eval_sane_material(self):
        up_queen = evaluation("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
        self.assertGreater(up_queen, 700)
        self.assertLess(evaluation("3qk3/8/8/8/8/8/8/4K3 w - - 0 1"), -700)


if __name__ == "__main__":
    unittest.main()
