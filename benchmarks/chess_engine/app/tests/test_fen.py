"""R3, R11: FEN parsing/serialisation round trips and position command handling."""
import unittest

from helpers import STARTPOS, run, fen_of, legal_moves

FENS = [
    STARTPOS,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
    "rnbqkbnr/ppp1pppp/8/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",
    "4k3/8/8/8/8/8/8/4K3 b - - 37 90",
    "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 b - - 5 10",
]


class FenTests(unittest.TestCase):
    def test_round_trip(self):
        for f in FENS:
            with self.subTest(fen=f):
                self.assertEqual(fen_of("position fen " + f), f)

    def test_startpos_equals_fen(self):
        self.assertEqual(fen_of("position startpos"), STARTPOS)

    def test_moves_update_fen(self):
        self.assertEqual(fen_of("position startpos moves e2e4"),
                         "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
        self.assertEqual(fen_of("position startpos moves e2e4 c7c5 g1f3"),
                         "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2")

    def test_castling_rights_lost(self):
        self.assertEqual(
            fen_of("position startpos moves e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 e1g1"),
            "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQ1RK1 b kq - 5 4")
        # rook move removes only that side's right
        self.assertEqual(
            fen_of("position fen r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1 moves h1h2"),
            "r3k2r/8/8/8/8/8/7R/R3K3 b Qkq - 1 1")
        # capturing a rook on its home square removes the right
        self.assertEqual(
            fen_of("position fen r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1 moves a1a8"),
            "R3k2r/8/8/8/8/8/8/4K2R b Kk - 0 1")

    def test_promotion_and_ep_moves_apply(self):
        self.assertEqual(fen_of("position fen 8/P6k/8/8/8/8/8/K7 w - - 0 1 moves a7a8n"),
                         "N7/7k/8/8/8/8/8/K7 b - - 0 1")
        self.assertEqual(fen_of("position fen 4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1 moves e5d6"),
                         "4k3/8/3P4/8/8/8/8/4K3 b - - 0 1")

    def test_fen_without_counters(self):
        self.assertEqual(fen_of("position fen 4k3/8/8/8/8/8/8/4K3 w - -"), "4k3/8/8/8/8/8/8/4K3 w - - 0 1")

    def test_invalid_fen_does_not_crash(self):
        for bad in ["position fen garbage", "position fen 8/8/8/8/8/8/8/8 w - - 0 1",
                    "position fen rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR x KQkq - 0 1",
                    "position fen 4k3/8/8/8/8/8/8/4K3 w - e3 0 1"]:
            with self.subTest(cmd=bad):
                lines = run([bad, "isready", "quit"])
                self.assertIn("readyok", lines)

    def test_illegal_move_ignored(self):
        self.assertEqual(fen_of("position startpos moves e2e5"), STARTPOS)

    def test_long_move_list_and_ucinewgame(self):
        lines = run(["position startpos moves g1f3 g8f6 f3g1 f6g8", "ucinewgame", "position startpos", "d", "quit"])
        self.assertIn("Fen: " + STARTPOS, lines)


if __name__ == "__main__":
    unittest.main()
