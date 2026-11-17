import unittest

from helpers import assemble, body, words
from agclib.numbers import dec_dp, dec_sp, parse_int, parse_octal_word
from agclib.model import AsmError


class NumberTests(unittest.TestCase):
    """R6: number formats."""

    def test_parse_int(self):
        self.assertEqual(parse_int("17"), 15)
        self.assertEqual(parse_int("17D"), 17)
        self.assertEqual(parse_int("-5"), -5)
        self.assertEqual(parse_int("+8"), 8)       # 8/9 digits fall back to decimal
        self.assertIsNone(parse_int("ABC"))

    def test_octal_words(self):
        self.assertEqual(parse_octal_word("123"), 0o123)
        self.assertEqual(parse_octal_word("-20000"), 0o57777)
        with self.assertRaises(AsmError):
            parse_octal_word("789")

    def test_dec_known_values(self):
        self.assertEqual(dec_sp(".0363551"), 0o1124)
        self.assertEqual(dec_sp(".7853134"), 0o31103)
        self.assertEqual(dec_sp("-.3216147"), 0o65552)
        self.assertEqual(dec_sp("-2001"), 0o74056)
        self.assertEqual(dec_sp("5 B-4"), 0o12000)
        self.assertEqual(dec_sp("1.5 B+4"), 0o30)
        self.assertEqual(dec_sp("E-5 B14"), 0o5174)
        self.assertEqual(dec_sp("-0"), 0o77777)
        self.assertEqual(dec_sp("0"), 0)

    def test_dec_dp(self):
        self.assertEqual(dec_dp("1.0 B-19"), (0, 0o1000))
        self.assertEqual(dec_dp("1.0 B-17"), (0, 0o4000))
        self.assertEqual(dec_dp("-1.0 B-19"), (0o77777, 0o76777))
        self.assertEqual(dec_dp(".999999999"), (0o37777, 0o37777))

    def test_huge_exponents_rejected_quickly(self):
        """R2: absurd scale factors must be diagnosed, not hang."""
        for t in ("1 B99999999999", "7777+12345678901234567890", "1E99999 B1"):
            with self.assertRaises(AsmError):
                dec_dp(t)

    def test_dec_overflow_is_error(self):
        with self.assertRaises(AsmError):
            dec_sp("99999")
        with self.assertRaises(AsmError):
            dec_sp("junk")


class PseudoOpTests(unittest.TestCase):
    """R6: constant and address pseudo-ops."""

    def test_data_words(self):
        a = assemble(body("\t\tOCT\t12", "\t\tOCTAL\t-1", "\t\tDEC\t100", "\t\t2DEC\t1.0 B-19",
                          "\t\t2OCT\t3777737777", "\t\tVN\t00125", "\t\tMM\t20",
                          "\t\tDEC*\t.5", "\t\t2DEC*\t.25"))
        self.assertEqual(words(a, 4, 11),
                         [0o12, 0o77776, 100, 0, 0o1000, 0o37777, 0o37777, (1 << 7) | 25, 20,
                          0o20000, 0o10000])

    def test_address_words(self):
        a = assemble(
            "\t\tSETLOC\t2123\n"
            "C\t\tERASE\n"                    # linear E4 address
            + body("L\t\tOCT\t0", "\t\tADRES\tL", "\t\tGENADR\tL", "\t\tREMADR\tL",
                   "\t\tCADR\tL", "\t\tFCADR\tL", "\t\tECADR\tC", "\t\tADRES\tC",
                   "\t\t-GENADR\tL", "\t\tADRES\tL +1"))
        w = words(a, 4, 10)
        self.assertEqual(w[1:4], [0o2000] * 3)
        self.assertEqual(w[4:6], [0o4 << 10] * 2)
        self.assertEqual(w[6], 0o2123)
        self.assertEqual(w[7], 0o1400 + 0o123)
        self.assertEqual(w[8], 0o75777)
        self.assertEqual(w[9], 0o2001)

    def test_two_word_cadrs_and_bbcon(self):
        a = assemble("X\t\tERASE\n\t\tSETLOC\t1400\nY\t\tERASE\n"
                     + body("\t\tEBANK=\tY", "L\t\tOCT\t0", "\t\t2CADR\tL", "\t\tBBCON\tL",
                            "\t\t-2CADR\tL"))
        w = words(a, 4, 6)
        self.assertEqual(w[1:3], [0o2000, (4 << 10) | 3])
        self.assertEqual(w[3], (4 << 10) | 3)
        self.assertEqual(w[4:6], [0o75777, 0o77777 - ((4 << 10) | 3)])

    def test_super_bank_cadr(self):
        a = assemble(body("L\t\tOCT\t0", "\t\tCADR\tL", "\t\tBBCON\tL", bank=0o42))
        self.assertEqual(a.fixed[0o42][1], 0o32 << 10)      # FBANK 32 aliases bank 42
        self.assertEqual(a.fixed[0o42][2], (0o32 << 10) | 0o100)

    def test_downlink_words(self):
        a = assemble("T\t\tEQUALS\t24\n"
                     + body("L\t\tOCT\t0", "\t\t1DNADR\tT", "\t\t6DNADR\tT", "\t\tDNCHAN\t30",
                            "\t\tDNPTR\tL", "\t\t-1DNADR\tT"))
        self.assertEqual(words(a, 4, 6)[1:], [0o24, 0o5 << 12 | 0o24, 0o7 << 12 | 0o30,
                                              0o6 << 12 | 0o2000, 0o77777 - 0o24])

    def test_equates(self):
        a = assemble("X\t=\t5\nY\tEQUALS\tX +2\nZ\t=MINUS\tX\n" + body("\t\tCA\tY"))
        self.assertEqual(a.vals["Y"].lin, 7)
        self.assertEqual(a.fixed[4][0], 0o30007)

    def test_forward_equate(self):
        a = assemble("Y\tEQUALS\tL +1\n" + body("L\t\tOCT\t0", "\t\tCA\tY"))
        self.assertEqual(a.fixed[4][1], 0o32001)

    def test_erase_forms(self):
        a = assemble("A\t\tERASE\nB\t\tERASE\t+3\nC\t\tERASE\nD\t\tERASE\t1357 - 1377\nE\t\tERASE\n")
        v = {k: a.vals[k].lin for k in "ABCDE"}
        self.assertEqual(v, {"A": 0, "B": 1, "C": 5, "D": 0o1357, "E": 0o1400})

    def test_symbol_redefinition_error(self):
        a = assemble("A\tEQUALS\t1\nA\tEQUALS\t2\n", expect_ok=False)
        self.assertTrue(any("redefined" in str(d) for d in a.diags))

    def test_undefined_symbol_error(self):
        a = assemble(body("\t\tCA\tNOWHERE"), expect_ok=False)
        self.assertTrue(any("NOWHERE" in str(d) for d in a.diags))

    def test_unknown_operation_error(self):
        a = assemble(body("\t\tBOGUS\t1"), expect_ok=False)
        self.assertTrue(any("BOGUS" in str(d) for d in a.diags))

    def test_typo_symbol_resolved_with_warning(self):
        a = assemble(body("LONGNAME\tOCT\t1", "\t\tCA\tLONGNAMX"))
        self.assertEqual(a.fixed[4][1], 0o32000)
        self.assertEqual(len(a.warnings), 1)

    def test_vn_requires_digits(self):
        a = assemble(body("\t\tVN\tXYZ"), expect_ok=False)
        self.assertTrue(a.diags)


if __name__ == "__main__":
    unittest.main()
