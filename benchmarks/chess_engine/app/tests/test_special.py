"""R4, R12: special moves, mates, stalemate, draws."""
import unittest

from helpers import legal_moves, run, bestmove


def moves(fen):
    return legal_moves("position fen " + fen)


def last_score(lines):
    info = [l for l in lines if l.startswith("info") and " score " in l]
    return info[-1].split(" score ")[1].split(" nodes")[0]


class SpecialMoveTests(unittest.TestCase):
    def test_castling_both_sides(self):
        m = moves("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.assertIn("e1g1", m)
        self.assertIn("e1c1", m)
        m = moves("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1")
        self.assertIn("e8g8", m)
        self.assertIn("e8c8", m)

    def test_castling_through_check_forbidden(self):
        m = moves("3k1r2/8/8/8/8/8/8/R3K2R w KQ - 0 1")  # f1 attacked
        self.assertNotIn("e1g1", m)
        self.assertIn("e1c1", m)

    def test_castling_into_check_forbidden(self):
        m = moves("3k2r1/8/8/8/8/8/8/R3K2R w KQ - 0 1")  # g1 attacked
        self.assertNotIn("e1g1", m)
        self.assertIn("e1c1", m)

    def test_castling_out_of_check_forbidden(self):
        m = moves("4r2k/8/8/8/8/8/8/R3K2R w KQ - 0 1")
        self.assertNotIn("e1g1", m)
        self.assertNotIn("e1c1", m)

    def test_queenside_rook_square_attacked_is_ok(self):
        m = moves("1r1k4/8/8/8/8/8/8/R3K2R w KQ - 0 1")  # b1 attacked, king path is not
        self.assertIn("e1c1", m)

    def test_castling_blocked_by_piece(self):
        m = moves("r3k2r/8/8/8/8/8/8/RN2K1NR w KQkq - 0 1")
        self.assertNotIn("e1g1", m)
        self.assertNotIn("e1c1", m)

    def test_no_castling_without_rights(self):
        m = moves("r3k2r/8/8/8/8/8/8/R3K2R w kq - 0 1")
        self.assertNotIn("e1g1", m)

    def test_en_passant_available(self):
        m = moves("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        self.assertIn("e5d6", m)

    def test_en_passant_horizontal_pin(self):
        m = moves("7k/8/8/KPp4r/8/8/8/8 w - c6 0 1")
        self.assertNotIn("b5c6", m)
        self.assertIn("b5b6", m)

    def test_en_passant_discovered_check_on_capture_resolves(self):
        # pawn d5 gives check to king e4... capturing the checker by ep is legal
        m = moves("8/8/8/2k5/3Pp3/8/8/4K3 b - d3 0 1")
        self.assertIn("e4d3", m)

    def test_promotions_all_pieces(self):
        m = moves("8/P6k/8/8/8/8/8/K7 w - - 0 1")
        for p in "qrbn":
            self.assertIn("a7a8" + p, m)
        self.assertNotIn("a7a8", m)
        m = moves("1n5k/P7/8/8/8/8/8/K7 w - - 0 1")
        for p in "qrbn":
            self.assertIn("a7b8" + p, m)

    def test_black_promotion(self):
        m = moves("7k/8/8/8/8/8/p7/6K1 b - - 0 1")
        self.assertEqual(sorted(x for x in m if x.startswith("a2")), ["a2a1b", "a2a1n", "a2a1q", "a2a1r"])

    def test_pinned_piece_cannot_move(self):
        m = moves("4r2k/8/8/8/8/8/4N3/4K3 w - - 0 1")
        self.assertFalse([x for x in m if x.startswith("e2")])

    def test_must_resolve_check(self):
        m = moves("4r2k/8/8/8/8/8/8/4K3 w - - 0 1")
        self.assertEqual(sorted(m), ["e1d1", "e1d2", "e1f1", "e1f2"])

    def test_checkmate_no_moves_and_bestmove_0000(self):
        cmd = "position startpos moves f2f3 e7e5 g2g4 d8h4"
        self.assertEqual(legal_moves(cmd), [])
        bm, lines = bestmove(cmd, "go depth 3")
        self.assertEqual(bm, "0000")

    def test_stalemate_no_moves(self):
        cmd = "position fen 7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
        self.assertEqual(legal_moves(cmd), [])
        bm, lines = bestmove(cmd, "go depth 3")
        self.assertEqual(bm, "0000")

    def test_fifty_move_rule_draw(self):
        bm, lines = bestmove("position fen 8/8/8/4k3/8/8/8/R3K3 w - - 100 80", "go depth 4")
        self.assertEqual(last_score(lines), "cp 0")
        bm, lines = bestmove("position fen 8/8/8/4k3/8/8/8/R3K3 w - - 0 80", "go depth 4")
        self.assertTrue(last_score(lines).startswith("cp ") and int(last_score(lines)[3:]) > 300)

    def test_insufficient_material_draw(self):
        for fen in ["8/8/8/4k3/8/8/8/4KN2 w - - 0 1", "8/8/8/4k3/8/8/8/4KB2 w - - 0 1", "8/8/8/4k3/8/8/8/4K3 w - - 0 1"]:
            with self.subTest(fen=fen):
                bm, lines = bestmove("position fen " + fen, "go depth 5")
                self.assertEqual(last_score(lines), "cp 0")

    def test_repetition_history_handled(self):
        """R12: search copes with repeated history and still returns a legal move."""
        cmd = "position startpos moves g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1"
        bm, lines = bestmove(cmd, "go depth 4")
        self.assertIn(bm, legal_moves(cmd))


    def test_threefold_repetition_is_a_draw_in_search(self):
        """R12: bare king vs K+Q. Position B has occurred twice; Kh1-g1 would make it a third
        occurrence, i.e. a draw, which beats every other (mated-soon) line for the hopeless side."""
        cycle = "h1g1 a5a6 g1h1 a6a5"
        cmd = "position fen 8/8/8/q3k3/8/8/8/7K w - - 0 1 moves " + cycle + " " + cycle
        bm, lines = bestmove(cmd, "go depth 6")
        self.assertEqual(bm, "h1g1")
        self.assertEqual(last_score(lines), "cp 0")
        # without the history the same position is lost (large negative score)
        bm2, lines2 = bestmove("position fen 8/8/8/q3k3/8/8/8/7K w - - 0 1", "go depth 6")
        self.assertLess(int(last_score(lines2)[3:]) if last_score(lines2).startswith("cp") else -99999, -500)


if __name__ == "__main__":
    unittest.main()
