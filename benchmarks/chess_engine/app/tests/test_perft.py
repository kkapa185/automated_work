"""R4, R5, R6: perft against published chessprogramming.org values."""
import time
import unittest

from helpers import STARTPOS, perft, divide

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
POS3 = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"
POS4 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
POS4M = "r2q1rk1/pP1p2pp/Q4n2/bbp1p3/Np6/1B3NBn/pPPP1PPP/R3K2R b KQ - 0 1"
POS5 = "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"
POS6 = "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"

CASES = [
    ("start", None, [20, 400, 8902, 197281, 4865609]),
    ("kiwipete", KIWIPETE, [48, 2039, 97862, 4085603]),
    ("pos3", POS3, [14, 191, 2812, 43238, 674624]),
    ("pos4", POS4, [6, 264, 9467, 422333]),
    ("pos4m", POS4M, [6, 264, 9467, 422333]),
    ("pos5", POS5, [44, 1486, 62379, 2103487]),
    ("pos6", POS6, [46, 2079, 89890, 3894594]),
]


class PerftTests(unittest.TestCase):
    def test_published_values(self):
        for name, fen, counts in CASES:
            for d, expected in enumerate(counts, 1):
                with self.subTest(pos=name, depth=d):
                    self.assertEqual(perft(fen, d)[0], expected)

    def test_output_format(self):
        """R5: '<move>: <count>' lines, blank line, 'Nodes searched: N'."""
        _, lines = perft(None, 1)
        self.assertEqual(len(lines), 20 + 2)
        body = [l for l in lines if l]
        self.assertEqual(body[-1], "Nodes searched: 20")
        self.assertEqual(lines[-2], "")
        self.assertIn("e2e4: 1", lines)
        self.assertIn("g1f3: 1", lines)

    def test_divide_start_depth2(self):
        d = divide(None, 2)
        self.assertEqual(len(d), 20)
        self.assertTrue(all(v == 20 for v in d.values()))

    def test_kiwipete_depth4_fast(self):
        """R6: Kiwipete perft 4 in well under a minute."""
        t = time.time()
        self.assertEqual(perft(KIWIPETE, 4)[0], 4085603)
        self.assertLess(time.time() - t, 60)


if __name__ == "__main__":
    unittest.main()
