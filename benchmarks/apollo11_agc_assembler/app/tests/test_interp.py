import unittest

from helpers import assemble, body, words
from agclib import interp as ip
from agclib.model import AsmError, comp15


def pair(left, right):
    return comp15(((left + 1) << 7) | (right + 1))


PRE = "\t\tSETLOC\t100\nX\t\tERASE\t+7\nY\t\tERASE\t+7\n"


def code(*lines, bank=4, expect_ok=True):
    return assemble(PRE + body("INTPRET\t\tOCT\t0", "\t\tTC\tINTPRET", *lines, bank=bank), expect_ok)


class InterpretiveTests(unittest.TestCase):
    """R7: interpretive language packing and operands."""

    def test_classification(self):
        self.assertEqual(ip.classify("EXIT").code, 0)
        self.assertEqual(ip.classify("SQRT").code, 0o10)
        self.assertEqual(ip.classify("PUSH").code, 0o170)
        self.assertEqual(ip.classify("VLOAD").code, 1)
        self.assertEqual(ip.classify("VLOAD*").code, 3)
        self.assertEqual(ip.classify("DLOAD").code, 0o06 * 4 + 1)
        self.assertEqual(ip.classify("AXT,1").code, 0o6)
        self.assertEqual(ip.classify("AXT,2").code, 0o2)
        self.assertEqual(ip.classify("GOTO").code, 8 * 0o12 + 4 + 2)
        self.assertEqual(ip.classify("SL1").code, 4)
        self.assertEqual(ip.classify("SR2R").code, (1 << 5) | 0o10 | 0o20 | 4)
        self.assertEqual(ip.classify("VSL3").code, (2 << 4) | 4)
        with self.assertRaises(AsmError):
            ip.classify("AXT")

    def test_pair_packing_first_op_in_low_bits(self):
        a = code("\t\tDLOAD\tDMP", "\t\t\tX", "\t\t\tY")
        w = words(a, 4, 5, 2)
        self.assertEqual(w[0], pair(ip.classify("DMP").code, ip.classify("DLOAD").code))
        self.assertEqual(w[1], 0o100 + 1)
        self.assertEqual(w[2], 0o110 + 1)

    def test_single_op_and_exit(self):
        a = code("\t\tEXIT", "\t\tCA\tX")
        self.assertEqual(words(a, 4, 2, 2), [comp15(1), 0o30100])

    def test_push_up_has_no_operand_word(self):
        a = code("\t\tDLOAD", "\t\t\tX", "\t\tDAD", "\t\tPUSH")
        self.assertEqual(len([w for w in words(a, 4, 6, 2) if w is not None]), 4)

    def test_mandatory_operand_missing_is_error(self):
        a = assemble(PRE + body("INTPRET\t\tOCT\t0", "\t\tTC\tINTPRET", "\t\tSLOAD", "\t\tEXIT"),
                     expect_ok=False)
        self.assertTrue(any("missing operand" in str(d) for d in a.diags))

    def test_mandatory_goes_to_later_op(self):
        # VXV pushes up, PDVL takes the single operand
        a = code("\t\tVXV\tPDVL", "\t\t\tX")
        self.assertEqual(words(a, 4, 1, 3), [0o101])

    def test_store_codes(self):
        a = code("\t\tSTORE\tX +1", "\t\tSTORE\tX,1", "\t\tSTORE\tX,2", "\t\tSTODL\tY",
                 "\t\t\tX", "\t\tSTOVL*\tY", "\t\t\tX,1", "\t\tSTORE\tY")
        w = words(a, 4, 8, 2)
        self.assertEqual(w[0], 0o101 + 1)
        self.assertEqual(w[1], (1 << 11 | 0o100) + 1)
        self.assertEqual(w[2], (2 << 11 | 0o100) + 1)
        self.assertEqual(w[3], (3 << 11 | 0o110) + 1)
        self.assertEqual(w[4], 0o101)
        self.assertEqual(w[5], (6 << 11 | 0o110) + 1)
        self.assertEqual(w[6], 0o101)

    def test_stadr_complements_following_store(self):
        a = code("\t\tVLOAD", "\t\t\tX", "\t\tSTADR", "\t\tSTORE\tY")
        self.assertEqual(words(a, 4, 1, 5)[0], comp15(0o110 + 1))

    def test_stcall_takes_cadr(self):
        a = code("\t\tSTCALL\tY", "\t\t\tINTPRET")
        w = words(a, 4, 2, 2)
        self.assertEqual(w, [(7 << 11 | 0o110) + 1, (4 << 10) | 0])

    def test_indexed_operands(self):
        a = code("\t\tDLOAD*", "\t\t\tX,1", "\t\tDLOAD*", "\t\t\tX,2")
        w = words(a, 4, 4, 2)
        self.assertEqual(w[1], 0o101)
        self.assertEqual(w[3], comp15(0o101))

    def test_indexed_requires_star(self):
        a = assemble(PRE + body("INTPRET\t\tOCT\t0", "\t\tTC\tINTPRET", "\t\tDLOAD", "\t\t\tX,1"),
                     expect_ok=False)
        self.assertTrue(a.diags)

    def test_shifts(self):
        a = code("\t\tSR\tDAD", "\t\t\t5", "\t\tSLR*", "\t\t\t0 -6,1", "\t\tSL1R\tVSR2")
        w = words(a, 4, 5, 2)
        self.assertEqual(w[1], 0o20000 + 0o400 + 0o200 + 5 + 1)
        self.assertEqual(w[3], 0o20000 + 0o1000 + 0o172 + 1)

    def test_misc_ops(self):
        a = code("\t\tAXT,1\tSSP", "\t\t\t3", "\t\t\tX", "\t\t\t6", "\t\tLXA,2", "\t\t\tY",
                 "\t\tGOTO", "\t\t\tINTPRET", "\t\tBZE", "\t\t\t+1")
        w = words(a, 4, 9, 2)
        self.assertEqual(w[1], 3)                          # raw AXT operand
        self.assertEqual(w[2], 0o101)                      # SSP address (+1)
        self.assertEqual(w[3], 6)                          # SSP raw value
        self.assertEqual(w[5], 0o110)                      # LXA raw ECADR
        self.assertEqual(w[7], 4 << 10)                    # GOTO CADR

    def test_relative_branch_target(self):
        # '+2' is relative to the operand word itself (word 4 -> word 6)
        a = code("\t\tBON\tSET", "\t\t\t3", "\t\t\t+2", "\t\t\t0")
        w = words(a, 4, 3, 3)
        self.assertEqual(w, [(0o14 << 4) | 3, (4 << 10) | 6, 0o03 << 4])

    def test_switches(self):
        a = code("\t\tSET", "\t\t\t3D", "\t\tCLEAR", "\t\t\t31D", "\t\tBOFF", "\t\t\t3D",
                 "\t\t\tINTPRET")
        w = words(a, 4, 7, 2)
        self.assertEqual(w[1], (0 << 8) | (0o03 << 4) | 3)
        self.assertEqual(w[3], (2 << 8) | (0o13 << 4) | 1)
        self.assertEqual(w[5], (0o16 << 4) | 3)
        self.assertEqual(w[6], 4 << 10)

    def test_data_pseudo_in_operand_slot(self):
        a = code("\t\tAXT,1\tSSP", "\t\tOCT\t3", "\t\t\tX", "\t\tOCT\t1")
        self.assertEqual(words(a, 4, 3, 3), [3, 0o101, 1])

    def test_exit_returns_to_basic_mode(self):
        a = code("\t\tDLOAD\tEXIT", "\t\t\tX", "\t\tINCR\tX")
        self.assertEqual(words(a, 4, 1, 4)[0], 0o24100)

    def test_unknown_mnemonic_inside_interpretive_code(self):
        a = assemble(PRE + body("INTPRET\t\tOCT\t0", "\t\tTC\tINTPRET", "\t\tNOSUCHOP"),
                     expect_ok=False)
        self.assertTrue(a.diags)


if __name__ == "__main__":
    unittest.main()
