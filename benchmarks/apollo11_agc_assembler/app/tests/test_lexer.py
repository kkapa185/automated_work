import os
import tempfile
import unittest


def _w(path, text):
    with open(path, "w") as fh:
        fh.write(text)


from helpers import assemble
from agclib.lexer import parse_line, read_source


class TokenizerTests(unittest.TestCase):
    """R3: tokenizer / parser."""

    def test_label_op_operand_comment(self):
        ln = parse_line("LABEL\tCA\tTWO\t# remark", "f", 3)
        self.assertEqual((ln.label, ln.fields, ln.lineno), ("LABEL", ["CA", "TWO"], 3))
        self.assertEqual(ln.op, "CA")
        self.assertEqual(ln.operand, "TWO")

    def test_no_label_when_indented(self):
        ln = parse_line("\t\tTC\tQ", "f", 1)
        self.assertIsNone(ln.label)
        self.assertEqual(ln.fields, ["TC", "Q"])

    def test_comment_and_blank(self):
        self.assertEqual(parse_line("# hello").kind, "comment")
        self.assertEqual(parse_line("   ").kind, "blank")
        self.assertEqual(parse_line("\t\tTC\tQ\t# x").fields, ["TC", "Q"])

    def test_label_only(self):
        ln = parse_line("ONLY")
        self.assertEqual((ln.label, ln.fields), ("ONLY", []))

    def test_relative_marker_is_not_a_label(self):
        self.assertIsNone(parse_line("-1\t\tADS\tX").label)
        self.assertEqual(parse_line(" +2\t\tCA\tX").fields, ["CA", "X"])

    def test_far_right_annotation_dropped(self):
        ln = parse_line("\t\tDLOAD\tSL2\t\t\t\t\t\tB2")
        self.assertEqual(ln.fields, ["DLOAD", "SL2"])

    def test_symbols_with_odd_characters(self):
        ln = parse_line("-1CHK\tTC\t-1CHK +1")
        self.assertEqual(ln.label, "-1CHK")
        self.assertEqual(ln.fields, ["TC", "-1CHK", "+1"])

    def test_include_expansion_and_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            _w(os.path.join(d, "A.agc"), "$B.agc\n# a\n")
            _w(os.path.join(d, "B.agc"), "\t\tTC\tQ\n$A.agc\n")
            diags = []
            lines = read_source(os.path.join(d, "A.agc"), diags)
            self.assertTrue(any("cycle" in str(x) for x in diags))
            self.assertTrue(any(l.fields == ["TC", "Q"] for l in lines))

    def test_missing_include_reported_with_location(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "M.agc")
            _w(p, "# x\n$NOPE.agc\n")
            diags = []
            read_source(p, diags)
            self.assertEqual(len(diags), 1)
            self.assertIn("M.agc:2:", str(diags[0]))

    def test_near_miss_include_used(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "M.agc")
            _w(p, "$GENERAL_THING.agc\n")
            _w(os.path.join(d, "GENERAL_THING.agc"), "\t\tTC\tQ\n")
            warns, diags = [], []
            lines = read_source(p, diags, warns=warns)
            self.assertFalse(diags)
            self.assertEqual(len(warns), 0)  # exact name -> no warning
            _w(p, "$THING.agc\n")
            lines = read_source(p, diags, warns=warns)
            self.assertFalse(diags)
            self.assertEqual(len(warns), 1)


if __name__ == "__main__":
    unittest.main()
