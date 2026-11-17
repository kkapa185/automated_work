import unittest

from helpers import assemble, body, words
from agclib.model import Val, saddr, cadr_of, fbank_of, add1c, comp15, ROPE_ORDER


class BankArithmeticTests(unittest.TestCase):
    """R5/R8: bank and address arithmetic, BNKSUM."""

    def test_value_helpers(self):
        self.assertEqual(saddr(Val("F", 4 * 0o2000 + 5)), 0o2005)
        self.assertEqual(saddr(Val("F", 2 * 0o2000 + 5)), 0o4005)
        self.assertEqual(saddr(Val("F", 3 * 0o2000 + 5)), 0o6005)
        self.assertEqual(saddr(Val("E", 0o1234)), 0o1234)
        self.assertEqual(saddr(Val("E", 0o2123)), 0o1523)
        self.assertEqual(cadr_of(Val("F", 0o12 * 0o2000 + 0o77)), (0o12 << 10) | 0o77)
        self.assertEqual(fbank_of(0o43), 0o33)
        self.assertEqual(add1c(0o77777, 1), 1)
        self.assertEqual(comp15(1), 0o77776)
        self.assertEqual(ROPE_ORDER[:4], [2, 3, 0, 1])
        self.assertEqual(len(ROPE_ORDER), 36)

    def test_fixed_fixed_addresses(self):
        a = assemble("\t\tBLOCK\t2\nL\t\tTC\tL\n\t\tBLOCK\t3\nM\t\tTC\tM\n")
        self.assertEqual(a.fixed[2][0], 0o4000)
        self.assertEqual(a.fixed[3][0], 0o6000)
        self.assertEqual(a.symbols["M"].val.lin, 3 * 0o2000)

    def test_bank_pointer_resumes(self):
        a = assemble("\t\tBANK\t5\n\t\tOCT\t1\n\t\tBANK\t6\n\t\tOCT\t2\n\t\tBANK\t5\n\t\tOCT\t3\n")
        self.assertEqual(words(a, 5, 3), [1, 3, None])
        self.assertEqual(words(a, 6, 2), [2, None])

    def test_setloc_symbolic_and_blank_bank(self):
        a = assemble("\t\tBANK\t5\nTAG\t\tEQUALS\n\t\tOCT\t1\n\t\tOCT\t2\n"
                     "\t\tBANK\t6\n\t\tSETLOC\tTAG\n\t\tBANK\n\t\tOCT\t3\n")
        self.assertEqual(words(a, 5, 4), [1, 2, 3, None])
        self.assertEqual(words(a, 6, 1), [None])

    def test_setloc_resume_after_label(self):
        a = assemble("\t\tBANK\t5\nL\t\tOCT\t1\n\t\tBANK\t6\n\t\tOCT\t7\n\t\tSETLOC\tL +1\n\t\tOCT\t2\n")
        self.assertEqual(words(a, 5, 2), [1, 2])

    def test_absolute_setloc(self):
        a = assemble("\t\tSETLOC\t4000\n\t\tOCT\t1\n\t\tSETLOC\t4010\n\t\tOCT\t2\n")
        self.assertEqual(words(a, 2, 9), [1] + [None] * 7 + [2])

    def test_overlap_is_error(self):
        a = assemble("\t\tBANK\t5\nL\t\tOCT\t1\n\t\tSETLOC\tL\n\t\tOCT\t2\n", expect_ok=False)
        self.assertTrue(any("occupied" in str(d) for d in a.diags))

    def test_bank_overflow_is_error(self):
        a = assemble("\t\tBANK\t5\n" + "\t\tOCT\t1\n" * 1025, expect_ok=False)
        self.assertTrue(any("overflow" in str(d) for d in a.diags))

    def test_bad_bank_number(self):
        a = assemble("\t\tBANK\t77\n", expect_ok=False)
        self.assertTrue(a.diags)

    def test_code_in_erasable_is_error(self):
        a = assemble("\t\tOCT\t1\n", expect_ok=False)
        self.assertTrue(a.diags)

    def test_erasable_symbol_addresses(self):
        a = assemble("\t\tSETLOC\t1400\nE3\t\tERASE\n\t\tSETLOC\t2000\nE4\t\tERASE\n"
                     + body("\t\tCA\tE3", "\t\tCA\tE4"))
        self.assertEqual(words(a, 4, 2), [0o31400, 0o31400])
        self.assertEqual(a.symbols["E4"].val.bank, 4)

    def test_bnksum_checksum_is_valid(self):
        a = assemble("\t\tBANK\t5\n\t\tBNKSUM\t5\n\t\tOCT\t12345\n\t\tOCT\t54321\n\t\tOCT\t7\n"
                     "\t\tBANK\t0\n\t\tBNKSUM\t0\n\t\tOCT\t1\n")
        for bank in (5, 0):
            total = 0
            for w in a.fixed[bank]:
                if w is not None:
                    total = add1c(total, w)
            self.assertIn(total, (bank, 0o77777) if bank == 0 else (bank,))
        self.assertIsNotNone(a.fixed[5][0o1777])
        rep = {r.bank: r for r in a.reports}
        self.assertEqual(rep[5].used, 4)
        self.assertEqual(rep[5].checksum, a.fixed[5][0o1777])

    def test_bnksum_conflict_reports_error(self):
        a = assemble("\t\tBANK\t5\n\t\tBNKSUM\t5\n\t\tSETLOC\t3777\n\t\tOCT\t1\n"
                     "\t\tBANK\t5\n\t\tSETLOC\t3777\n\t\tOCT\t2\n", expect_ok=False)
        self.assertTrue(a.diags)


if __name__ == "__main__":
    unittest.main()
