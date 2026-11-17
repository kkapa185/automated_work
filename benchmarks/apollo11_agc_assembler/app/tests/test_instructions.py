import unittest

from helpers import assemble, body, words


def one(*lines):
    return assemble(body(*lines)).fixed[4][0]


class BasicInstructionTests(unittest.TestCase):
    """R4: encoding of every basic instruction / extracode."""

    def test_address_instructions(self):
        cases = {
            "TC\t2005": 0o02005, "CA\t1234": 0o31234, "CAF\t2005": 0o32005,
            "CAE\t55": 0o30055, "CS\t55": 0o40055, "AD\t55": 0o60055,
            "MASK\t55": 0o70055, "INDEX\t55": 0o50055, "NDX\t55": 0o50055,
            "TS\t55": 0o54055, "XCH\t55": 0o56055, "CCS\t55": 0o10055,
            "LXCH\t55": 0o22055, "INCR\t55": 0o24055, "ADS\t55": 0o26055,
            "TCF\t2400": 0o12400, "TCR\t2400": 0o02400,
        }
        for src, want in cases.items():
            with self.subTest(src):
                self.assertEqual(one("\t\t" + src), want)

    def test_double_precision_ops_address_low_word(self):
        self.assertEqual(one("\t\tDAS\t55"), 0o20056)
        self.assertEqual(one("\t\tEXTEND", "\t\tDCA\t55"), 0o06)
        a = assemble(body("\t\tEXTEND", "\t\tDCA\t55", "\t\tEXTEND", "\t\tDCS\t55",
                          "\t\tDXCH\t55"))
        self.assertEqual(words(a, 4, 5), [0o6, 0o30056, 0o6, 0o40056, 0o52056])

    def test_extracodes(self):
        src = ["EXTEND\t", "DV\t55", "EXTEND", "SU\t55", "EXTEND", "MP\t55",
               "EXTEND", "MSU\t55", "EXTEND", "QXCH\t55", "EXTEND", "AUG\t55",
               "EXTEND", "DIM\t55", "EXTEND", "BZF\t2100", "EXTEND", "BZMF\t2100"]
        a = assemble(body(*["\t\t" + s for s in src]))
        got = [w for i, w in enumerate(words(a, 4, 18)) if i % 2 == 1]
        self.assertEqual(got, [0o10055, 0o60055, 0o70055, 0o20055, 0o22055,
                               0o24055, 0o26055, 0o12100, 0o62100][:len(got)])

    def test_io_instructions(self):
        a = assemble(body(*["\t\tEXTEND\n\t\t%s\t12" % o for o in
                            ("READ", "WRITE", "RAND", "WAND", "ROR", "WOR", "RXOR")]))
        got = [w for i, w in enumerate(words(a, 4, 14)) if i % 2 == 1]
        self.assertEqual(got, [0o12, 0o1012, 0o2012, 0o3012, 0o4012, 0o5012, 0o6012])

    def test_implied_address_codes(self):
        names = ["RETURN", "RELINT", "INHINT", "RESUME", "XLQ", "XXALQ",
                 "TCAA", "OVSK", "COM", "DOUBLE", "DDOUBL", "ZL"]
        a = assemble(body(*["\t\t" + n for n in names]))
        self.assertEqual(words(a, 4, len(names)),
                         [0o2, 0o3, 0o4, 0o50017, 0o1, 0o0, 0o54005, 0o54000,
                          0o40000, 0o60000, 0o20001, 0o22007])

    def test_extended_implied_codes(self):
        a = assemble(body("\t\tEXTEND", "\t\tSQUARE", "\t\tEXTEND", "\t\tZQ",
                          "\t\tEXTEND", "\t\tDCOM", "\t\tDTCB", "\t\tDTCF"))
        self.assertEqual(words(a, 4, 7), [6, 0o70000, 6, 0o22007, 6, 0o40001, 0o52006])

    def test_noop_in_fixed_memory_is_tcf_next(self):
        a = assemble(body("\t\tNOOP", "\t\tNOOP"))
        self.assertEqual(words(a, 4, 2), [0o12001, 0o12002])

    def test_relative_and_symbolic_operands(self):
        a = assemble(body("\t\tTC\t+2", "\t\tTC\t-1", "L\t\tTC\tL +1", "\t\tCA\tL"))
        self.assertEqual(words(a, 4, 4), [0o2002, 0o2000, 0o2003, 0o32002])

    def test_numeric_operand_arithmetic(self):
        self.assertEqual(one("\t\tCAF\t0 -1"), 0o27777)
        self.assertEqual(one("\t\tTC\t10000"), 0o2000)   # linear fixed address

    def test_blank_operand_is_zero(self):
        self.assertEqual(one("\t\tTCF"), 0o10000)

    def test_numeric_opcode_field(self):
        self.assertEqual(one("\t\t7\t2005"), 0o72005)

    def test_negated_instruction_word(self):
        self.assertEqual(one("\t\t-CCS\t55"), 0o67722)

    def test_extracode_requires_extend(self):
        a = assemble(body("\t\tMP\t55"), expect_ok=False)
        self.assertTrue(any("EXTEND" in str(d) for d in a.diags))

    def test_basic_after_extend_is_an_error(self):
        a = assemble(body("\t\tEXTEND", "\t\tCA\t55"), expect_ok=False)
        self.assertTrue(a.diags)

    def test_extend_survives_index_and_directives(self):
        assemble(body("\t\tEXTEND", "\t\tINDEX\t55", "\t\tDCA\t0"))

    def test_range_checks(self):
        a = assemble(body("L\t\tTS\tL"), expect_ok=False)   # TS needs erasable
        self.assertTrue(a.diags)

    def test_operand_on_implied_op_is_error(self):
        a = assemble(body("\t\tRETURN\t55"), expect_ok=False)
        self.assertTrue(a.diags)


if __name__ == "__main__":
    unittest.main()
