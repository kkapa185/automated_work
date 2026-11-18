"""R8, R10: tactical strength (mates) and play against a random mover."""
import random
import time
import unittest

from helpers import Engine, bestmove, legal_moves, run


def score_line(lines):
    info = [l for l in lines if l.startswith("info") and " score " in l]
    return info[-1].split(" score ")[1].split(" nodes")[0]


class MateTests(unittest.TestCase):
    def test_mate_in_one_back_rank(self):
        bm, lines = bestmove("position fen 6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1", "go depth 4")
        self.assertEqual(bm, "a1a8")
        self.assertEqual(score_line(lines), "mate 1")

    def test_mate_in_one_black_to_move(self):
        bm, lines = bestmove("position fen r5k1/8/8/8/8/8/5PPP/6K1 b - - 0 1", "go depth 4")
        self.assertEqual(bm, "a8a1")
        self.assertEqual(score_line(lines), "mate 1")

    def test_smothered_mate_in_one(self):
        bm, lines = bestmove("position fen 6rk/6pp/8/6N1/8/8/8/K7 w - - 0 1", "go depth 3")
        self.assertEqual(bm, "g5f7")
        self.assertEqual(score_line(lines), "mate 1")

    def test_mate_in_one_with_movetime(self):
        bm, lines = bestmove("position fen 6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1", "go movetime 300")
        self.assertEqual(bm, "a1a8")

    def test_mate_in_two(self):
        bm, lines = bestmove("position fen kbK5/pp6/1P6/8/8/8/8/R7 w - - 0 1", "go depth 6")
        self.assertEqual(bm, "a1a6")
        self.assertEqual(score_line(lines), "mate 2")

    def test_mate_in_three_queen_endgame(self):
        # K+Q vs K: mate is found within a few plies
        bm, lines = bestmove("position fen 7k/8/5K2/8/8/8/8/6Q1 w - - 0 1", "go depth 7")
        self.assertTrue(score_line(lines).startswith("mate "))

    def test_being_mated_reports_negative(self):
        # black to move, mated in 1 by white regardless? Black king trapped, white threatens Ra8#
        bm, lines = bestmove("position fen 6k1/5ppp/8/8/8/8/8/R3K3 b - - 0 1", "go depth 5")
        self.assertIn(bm, legal_moves("position fen 6k1/5ppp/8/8/8/8/8/R3K3 b - - 0 1"))

    def test_wins_material(self):
        # free queen: Bxd5 wins the undefended queen
        bm, _ = bestmove("position fen 4k3/8/8/3q4/8/5B2/8/4K3 w - - 0 1", "go depth 4")
        self.assertEqual(bm, "f3d5")


def engine_vs_random(engine_white, seed, max_plies=300, go="go movetime 60"):
    rng = random.Random(seed)
    moves = []
    e = Engine()
    try:
        for ply in range(max_plies):
            cmd = "position startpos" + (" moves " + " ".join(moves) if moves else "")
            white_to_move = ply % 2 == 0
            if white_to_move == engine_white:
                e.send(cmd)
                e.send(go)
                bm = [l for l in e.read_until("bestmove", 20) if l.startswith("bestmove")][0].split()[1]
                if bm == "0000":
                    return "engine_mated_or_stalemated", ply
                moves.append(bm)
            else:
                lm = legal_moves(cmd)
                if not lm:
                    # random side has no move: mate if in check
                    chk = [l for l in run([cmd, "d", "quit"]) if l.startswith("Checkers:")][0]
                    return ("engine_won" if chk.strip() != "Checkers:" else "stalemate"), ply
                moves.append(rng.choice(lm))
        return "unfinished", max_plies
    finally:
        e.close()


class RandomMoverTests(unittest.TestCase):
    def test_beats_random_as_white(self):
        res, ply = engine_vs_random(True, 1)
        self.assertEqual(res, "engine_won", (res, ply))

    def test_beats_random_as_black(self):
        res, ply = engine_vs_random(False, 2)
        self.assertEqual(res, "engine_won", (res, ply))


if __name__ == "__main__":
    unittest.main()
