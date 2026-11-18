import unittest
from tests.helpers import out, run


class ReviewFixes(unittest.TestCase):
    def test_row_values(self):
        self.assertEqual(out("select (1,2)=(1,2), (1,2)<(1,3), (1,null)=(1,2), (2,1)>(1,9), (1,2) in ((1,2),(3,4)), (5,6) not in ((1,2));\n"),
                         "1|1||1|1|1\n")

    def test_no_header_for_empty_result(self):
        self.assertEqual(out("create table e(a);\n.headers on\nselect * from e;\nselect 1 as x;\n"), "x\n1\n")

    def test_datetime_unixepoch_and_overflow(self):
        self.assertEqual(out("select datetime(0,'unixepoch'), datetime(1e20), date('2021-03-31','+1 month');\n"),
                         "1970-01-01 00:00:00||2021-05-01\n")

    def test_correlated_subquery_uses_hash_lookup(self):
        s = "create table t(a);\ncreate table u(a);\nbegin;\n" + "".join(
            "insert into t values(%d);insert into u values(%d);\n" % (i, i * 2) for i in range(3000)) + \
            "commit;\nselect count(*) from t where exists(select 1 from u where u.a = t.a);\n"
        self.assertEqual(out(s), "1500\n")

    def test_hash_cache_sees_updates(self):
        s = "create table t(a);\ncreate table u(a);\ninsert into t values(1),(2);\ninsert into u values(1);\n" \
            "select (select count(*) from u where u.a = t.a) from t;\ninsert into u values(2);\nselect (select count(*) from u where u.a = t.a) from t;\n"
        self.assertEqual(out(s), "1\n0\n1\n1\n")


if __name__ == '__main__':
    unittest.main()


class ContinueAfterError(unittest.TestCase):
    def test_same_line_statements_continue(self):
        o, e, rc = run("select 1; select * from nosuch; select 3;\nselec 4; select 5;\n")
        self.assertEqual(o, "1\n3\n5\n")
        self.assertEqual(e.splitlines(), ["Parse error near line 1: no such table: nosuch",
                                          'Parse error near line 2: near "selec": syntax error'])
        self.assertEqual(rc, 1)
