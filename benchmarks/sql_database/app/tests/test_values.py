import unittest
from dbengine import values as V
from dbengine.tokenizer import tokenize
from dbengine.parser import Parser
from dbengine.errors import SqlError


class FormatReal(unittest.TestCase):
    def test_known(self):
        self.assertEqual(V.format_real(3.0), '3.0')
        self.assertEqual(V.format_real(1e20), '1.0e+20')
        self.assertEqual(V.format_real(2.0 ** 63), '9.2233720368547758e+18')
        self.assertEqual(V.format_real(float('inf')), 'Inf')
        self.assertEqual(V.format_real(float('-inf')), '-Inf')
        self.assertEqual(V.format_real(0.5), '0.5')
        self.assertEqual(V.format_real(1.5e-7), '1.5e-07')
        self.assertEqual(V.format_real(-0.0), '-0.0')


class Affinity(unittest.TestCase):
    def test_declared_type_rules(self):
        self.assertEqual(V.type_affinity('INT'), 'INTEGER')
        self.assertEqual(V.type_affinity('BIGINT'), 'INTEGER')
        self.assertEqual(V.type_affinity('VARCHAR(10)'), 'TEXT')
        self.assertEqual(V.type_affinity('CLOB'), 'TEXT')
        self.assertEqual(V.type_affinity(''), 'BLOB')
        self.assertEqual(V.type_affinity('BLOB'), 'BLOB')
        self.assertEqual(V.type_affinity('DOUBLE'), 'REAL')
        self.assertEqual(V.type_affinity('FLOAT'), 'REAL')
        self.assertEqual(V.type_affinity('DECIMAL(10,5)'), 'NUMERIC')
        self.assertEqual(V.type_affinity('BOOLEAN'), 'NUMERIC')

    def test_apply(self):
        self.assertEqual(V.apply_affinity('12', 'INTEGER'), 12)
        self.assertEqual(V.apply_affinity('1.0', 'INTEGER'), 1)
        self.assertEqual(V.apply_affinity('abc', 'INTEGER'), 'abc')
        self.assertEqual(V.apply_affinity(5, 'REAL'), 5.0)
        self.assertEqual(V.apply_affinity(5, 'TEXT'), '5')
        self.assertEqual(V.apply_affinity(5.5, 'TEXT'), '5.5')
        self.assertEqual(V.apply_affinity('5', 'BLOB'), '5')
        self.assertEqual(V.apply_affinity(3.0, 'NUMERIC'), 3)


class Arithmetic(unittest.TestCase):
    def test_overflow_to_real(self):
        self.assertEqual(V.add(V.INT_MAX, 1), 9.2233720368547758e18)
        self.assertEqual(V.mul(V.INT_MAX, 2), 1.8446744073709552e19)

    def test_division_and_mod(self):
        self.assertEqual(V.div(7, 2), 3)
        self.assertEqual(V.div(-7, 2), -3)
        self.assertEqual(V.div(7, 0), None)
        self.assertEqual(V.mod(-7, 3), -1)
        self.assertEqual(V.mod(7, 0), None)
        self.assertEqual(V.mod(7.5, 2), 1.0)

    def test_text_to_number(self):
        self.assertEqual(V.add('12abc', 1), 13)
        self.assertEqual(V.add('abc', 1), 1)
        self.assertEqual(V.add(None, 1), None)

    def test_compare_classes(self):
        self.assertLess(V.compare(5, 'a'), 0)
        self.assertLess(V.compare('z', b'a'), 0)
        self.assertEqual(V.compare(1, 1.0), 0)
        self.assertEqual(V.compare('A', 'a', V.get_collation('NOCASE')), 0)
        self.assertEqual(V.compare('a ', 'a', V.get_collation('RTRIM')), 0)


class Tokenizer(unittest.TestCase):
    def kinds(self, s):
        return [(t.kind, t.val) for t in tokenize(s)[:-1]]

    def test_basic(self):
        self.assertEqual(self.kinds("select 'it''s', \"Col\", x'0aFF', 1.5e3, 0x10"),
                         [('id', 'select'), ('str', "it's"), ('op', ','), ('qid', 'Col'), ('op', ','),
                          ('blob', b'\x0a\xff'), ('op', ','), ('float', 1500.0), ('op', ','), ('int', 16)])

    def test_comments(self):
        self.assertEqual(self.kinds('1 -- c\n/* x */ 2'), [('int', 1), ('int', 2)])

    def test_bad(self):
        self.assertEqual(tokenize("'abc")[0].kind, 'bad')


class ParserErrors(unittest.TestCase):
    def test_syntax_error_message(self):
        with self.assertRaises(SqlError) as cm:
            Parser('select from').parse_statement()
        self.assertEqual(cm.exception.msg, 'near "from": syntax error')

    def test_incomplete(self):
        with self.assertRaises(SqlError) as cm:
            Parser('select 1 +').parse_statement()
        self.assertEqual(cm.exception.msg, 'incomplete input')


if __name__ == '__main__':
    unittest.main()
