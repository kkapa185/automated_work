import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

from helpers import ROOT
from agclib.assembler import Assembler
from agclib.model import ROPE_ORDER, add1c

AGCASM = os.path.join(ROOT, "agcasm")
SRC = os.path.join(ROOT, "agc_source")


def jload(path):
    with open(path) as fh:
        return json.load(fh)


def run(*args):
    return subprocess.run([sys.executable, AGCASM, *args], cwd=ROOT,
                          capture_output=True, text=True)


def parse_rope(path):
    banks, cur = {}, None
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith("BANK="):
                cur = int(line[5:], 8)
                banks[cur] = []
            else:
                banks[cur].extend(line.split())
    return banks


class CliTests(unittest.TestCase):
    """R1/R2: command line behaviour and diagnostics."""

    def test_no_command(self):
        r = run()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_missing_source(self):
        r = run("assemble", "no/such/MAIN.agc", "-o", "out/x.bin")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no/such/MAIN.agc:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_diagnostics_have_file_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "MAIN.agc")
            with open(p, "w") as fh:
                fh.write("\t\tBANK\t4\n\t\tBOGUS\t1\n\t\tCA\tNOPE\n\t\tOCT\t99\n")
            r = run("assemble", p, "-o", os.path.join(d, "o.bin"))
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("Traceback", r.stderr)
            self.assertRegex(r.stderr, re.escape(p) + r":2: unknown operation 'BOGUS'")
            self.assertIn(":3: undefined symbol 'NOPE'", r.stderr)
            self.assertIn(":4:", r.stderr)
            self.assertFalse(os.path.exists(os.path.join(d, "o.bin")))

    def test_small_program_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "MAIN.agc")
            with open(p, "w") as fh:
                fh.write("A\t\tEQUALS\t5\n\t\tBANK\t4\nL\t\tTC\tL\n\t\tBNKSUM\t4\n")
            out = os.path.join(d, "sub", "o.binsource")
            sym = os.path.join(d, "o.json")
            lst = os.path.join(d, "o.lst")
            r = run("assemble", p, "-o", out, "--symbols", sym, "--listing", lst)
            self.assertEqual(r.returncode, 0, r.stderr)
            banks = parse_rope(out)
            self.assertEqual(banks[4][0], "02000")
            self.assertEqual(banks[4][1], "@")
            symbols = jload(sym)
            self.assertEqual(symbols["A"]["kind"], "constant")
            self.assertEqual(symbols["L"], {"value": 0o2000, "kind": "fixed", "bank": 4,
                                            "file": p, "line": 3})
            with open(lst) as fh:
                    text = fh.read()
            self.assertIn("04,2000  02000", text)
            self.assertIn("bank  checksum", r.stdout)


class EndToEndTests(unittest.TestCase):
    """R9-R13: assemble both flight programs."""

    @classmethod
    def setUpClass(cls):
        cls.results = {}
        cls.tmp = tempfile.TemporaryDirectory()
        for prog in ("Comanche055", "Luminary099"):
            main = os.path.join(SRC, prog, "MAIN.agc")
            if not os.path.exists(main):
                continue
            out = os.path.join(cls.tmp.name, prog + ".binsource")
            sym = os.path.join(cls.tmp.name, prog + ".json")
            lst = os.path.join(cls.tmp.name, prog + ".lst")
            r = run("assemble", main, "-o", out, "--symbols", sym, "--listing", lst)
            cls.results[prog] = (r, out, sym, lst)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def each(self):
        self.assertTrue(self.results, "flight software sources not found")
        return self.results.items()

    def test_assemble_without_errors(self):
        for prog, (r, *_rest) in self.each():
            with self.subTest(prog):
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("error", r.stderr.replace("0 error", ""))

    def test_rope_format(self):
        for prog, (r, out, *_rest) in self.each():
            with self.subTest(prog):
                with open(out) as fh:
                    text = fh.read().splitlines()
                heads = [l for l in text if l.startswith("BANK=")]
                self.assertEqual(heads, [f"BANK={b:o}" for b in ROPE_ORDER])
                self.assertTrue(text[0].startswith(";"))
                banks = parse_rope(out)
                for b, ws in banks.items():
                    self.assertEqual(len(ws), 1024)
                    for w in ws:
                        self.assertTrue(w == "@" or re.fullmatch(r"[0-7]{5}", w))
                # eight words per line
                body = [l for l in text if l and not l.startswith(("BANK=", ";"))]
                self.assertTrue(all(len(l.split()) == 8 for l in body))
                self.assertEqual(len(body), 36 * 128)

    def test_bank_checksums_valid(self):
        for prog, (r, out, *_rest) in self.each():
            with self.subTest(prog):
                for b, ws in parse_rope(out).items():
                    total = 0
                    for w in ws:
                        if w != "@":
                            total = add1c(total, int(w, 8))
                    self.assertIn(total, (b, 0o77777 if b == 0 else b), f"bank {b:o}")
                    self.assertNotEqual(ws[-1], "@")

    def test_summary_lists_every_bank(self):
        for prog, (r, *_rest) in self.each():
            with self.subTest(prog):
                rows = [l for l in r.stdout.splitlines()[1:] if l.strip()]
                self.assertEqual(len(rows), 36)

    def test_symbol_table(self):
        for prog, (r, out, sym, lst) in self.each():
            with self.subTest(prog):
                s = jload(sym)
                self.assertGreater(len(s), 5000)
                for name, e in s.items():
                    self.assertEqual(set(e), {"value", "kind", "bank", "file", "line"})
                    self.assertIn(e["kind"], ("fixed", "erasable", "constant"))
                    if e["kind"] == "fixed":
                        self.assertIn(e["bank"], range(0o44))
                        self.assertTrue(0o2000 <= e["value"] <= 0o7777)
                    if e["kind"] == "erasable":
                        self.assertTrue(0 <= e["value"] <= 0o1777)
                self.assertEqual(s["MPAC"]["kind"], "erasable")
                self.assertEqual(s["BANKCALL"]["bank"], 2)
                self.assertEqual(s["BANKCALL"]["value"] & 0o7000, 0o4000)

    def test_symbols_match_rope(self):
        """A label's address must index a non-empty rope word in its bank."""
        for prog, (r, out, sym, lst) in self.each():
            with self.subTest(prog):
                banks = parse_rope(out)
                s = jload(sym)
                checked = empty = 0
                for name, e in s.items():
                    if e["kind"] != "fixed":
                        continue
                    off = e["value"] & 0o1777
                    w = banks[e["bank"]][off]
                    checked += 1
                    empty += (w == "@")      # end-of-section tags point past the data
                self.assertGreater(checked, 4000)
                self.assertLess(empty, checked // 50)

    def test_listing(self):
        for prog, (r, out, sym, lst) in self.each():
            with self.subTest(prog):
                with open(lst) as fh:
                    text = fh.read()
                self.assertIn("BANKCALL", text)
                self.assertRegex(text, r"(?m)^02,4000  00004")

    def test_in_process_results_deterministic(self):
        prog = "Comanche055"
        main = os.path.join(SRC, prog, "MAIN.agc")
        if not os.path.exists(main):
            self.skipTest("sources missing")
        a1, a2 = Assembler(), Assembler()
        self.assertTrue(a1.assemble_file(main))
        self.assertTrue(a2.assemble_file(main))
        self.assertEqual(a1.fixed, a2.fixed)

    def test_known_structure(self):
        """Interrupt vectors sit at the start of bank 2, four words apiece."""
        for prog, (r, out, *_rest) in self.each():
            with self.subTest(prog):
                b2 = parse_rope(out)[2]
                self.assertEqual(b2[0], "00004")          # INHINT at the restart vector
                self.assertTrue(all(w != "@" for w in b2[:0o40]))


if __name__ == "__main__":
    unittest.main()
