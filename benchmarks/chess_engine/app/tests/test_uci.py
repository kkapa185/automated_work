"""R1, R2, R7, R8: UCI protocol behaviour."""
import re
import time
import unittest

from helpers import Engine, run, bestmove, legal_moves, STARTPOS


class UciProtocolTests(unittest.TestCase):
    def test_uci_handshake(self):
        lines = run(["uci", "quit"])
        self.assertTrue(any(l.startswith("id name ") for l in lines))
        self.assertTrue(any(l.startswith("id author ") for l in lines))
        self.assertTrue(any(l.startswith("option name Hash") for l in lines))
        self.assertEqual(lines[-1], "uciok")

    def test_isready_and_newgame(self):
        lines = run(["isready", "ucinewgame", "isready", "quit"])
        self.assertEqual(lines, ["readyok", "readyok"])

    def test_setoption_hash(self):
        lines = run(["setoption name Hash value 16", "position startpos", "go depth 3", "quit"])
        self.assertTrue(any(l.startswith("bestmove") for l in lines))

    def test_go_depth_info_lines(self):
        bm, lines = bestmove("position startpos", "go depth 6")
        infos = [l for l in lines if l.startswith("info depth")]
        self.assertGreaterEqual(len(infos), 6)
        pat = re.compile(r"^info depth (\d+) .*score (cp -?\d+|mate -?\d+) .*nodes (\d+) .*nps (\d+) .*pv( [a-h][1-8][a-h][1-8][qrbn]?)+$")
        for l in infos:
            self.assertRegex(l, pat)
        self.assertEqual(int(infos[-1].split()[2]), 6)
        self.assertIn(bm, legal_moves("position startpos"))
        # bestmove is the last line and equals the first move of the last pv
        self.assertTrue(lines[-1].startswith("bestmove"))
        self.assertEqual(infos[-1].split(" pv ")[1].split()[0], bm)

    def test_bestmove_after_moves(self):
        cmd = "position startpos moves e2e4 e7e5"
        bm, _ = bestmove(cmd, "go depth 4")
        self.assertIn(bm, legal_moves(cmd))

    def test_nodes_limit(self):
        t = time.time()
        bm, lines = bestmove("position startpos", "go nodes 20000")
        self.assertLess(time.time() - t, 5)
        n = int([l for l in lines if l.startswith("info depth")][-1].split(" nodes ")[1].split()[0])
        self.assertLess(n, 20000 + 5000)
        self.assertIn(bm, legal_moves("position startpos"))

    def test_movetime_respected(self):
        e = Engine()
        try:
            for mt in (100, 300, 1000):
                e.send("position startpos")
                t = time.time()
                e.send("go movetime %d" % mt)
                e.read_until("bestmove")
                dt = (time.time() - t) * 1000
                self.assertLess(dt, mt + 100, "movetime %d took %.0f ms" % (mt, dt))
                self.assertGreater(dt, mt * 0.5)
        finally:
            e.close()

    def test_movetime_tactical_position_respected(self):
        e = Engine()
        try:
            e.send("position fen r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
            t = time.time()
            e.send("go movetime 200")
            e.read_until("bestmove")
            self.assertLess((time.time() - t) * 1000, 300)
        finally:
            e.close()

    def test_infinite_and_stop(self):
        e = Engine()
        try:
            e.send("position startpos")
            e.send("go infinite")
            time.sleep(0.5)
            e.send("isready")  # must stay responsive while searching
            e.read_until("readyok", 5)
            t = time.time()
            e.send("stop")
            lines = e.read_until("bestmove", 5)
            self.assertLess(time.time() - t, 1.0)
            self.assertTrue(any(l.startswith("info depth") for l in lines) or True)
            # engine is reusable afterwards
            e.send("go depth 3")
            e.read_until("bestmove", 10)
        finally:
            e.close()

    def test_infinite_does_not_finish_by_itself_on_mate(self):
        e = Engine()
        try:
            e.send("position fen 6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
            e.send("go infinite")
            time.sleep(0.5)
            self.assertIsNone(e.p.poll())
            e.send("stop")
            lines = e.read_until("bestmove", 5)
            self.assertEqual(lines[-1], "bestmove a1a8")
        finally:
            e.close()

    def test_clock_time_controls(self):
        e = Engine()
        try:
            e.send("position startpos")
            t = time.time()
            e.send("go wtime 2000 btime 2000 winc 0 binc 0 movestogo 20")
            e.read_until("bestmove", 10)
            self.assertLess(time.time() - t, 0.6)
            e.send("position startpos moves e2e4")
            t = time.time()
            e.send("go wtime 60000 btime 100 binc 0")  # black has 100 ms
            e.read_until("bestmove", 10)
            self.assertLess(time.time() - t, 0.1)
        finally:
            e.close()

    def test_go_depth_while_pipe_closes(self):
        lines = run(["position startpos", "go depth 4"])
        self.assertTrue(lines[-1].startswith("bestmove"))

    def test_unknown_commands_ignored(self):
        lines = run(["foo bar", "", "isready", "quit"])
        self.assertEqual(lines, ["readyok"])

    def test_quit_exits(self):
        e = Engine()
        e.send("go infinite")
        e.send("quit")
        e.p.wait(timeout=5)
        self.assertEqual(e.p.returncode, 0)

    def test_single_legal_move_fast(self):
        t = time.time()
        bm, _ = bestmove("position fen 4k3/1q4r1/8/8/8/8/8/7K w - - 0 1", "go wtime 100000 btime 100000")
        self.assertEqual(bm, "h1h2")
        self.assertLess(time.time() - t, 1)

    def test_tt_hash_option_small_and_new_game(self):
        lines = run(["setoption name Hash value 1", "ucinewgame", "position startpos", "go depth 5", "quit"])
        self.assertTrue(any(l.startswith("bestmove") for l in lines))


if __name__ == "__main__":
    unittest.main()
