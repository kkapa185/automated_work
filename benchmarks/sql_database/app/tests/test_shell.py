import unittest
from tests.helpers import run, out


class OutputFormats(unittest.TestCase):
    def test_list_default(self):
        self.assertEqual(out("select 1, 'a', null, 2.5;\n"), "1|a||2.5\n")

    def test_numbers(self):
        self.assertEqual(out("select 3.0, 1e20, 9223372036854775807+1, 1.0e15, 0.1+0.2;\n"),
                         "3.0|1.0e+20|9.2233720368547758e+18|1.0e+15|0.3\n")
        self.assertEqual(out("select 1e999, -1e999;\n"), "Inf|-Inf\n")

    def test_headers_and_modes(self):
        s = "create table t(a,b);\ninsert into t values(1,'x'),(2,null);\n.headers on\nselect * from t;\n"
        self.assertEqual(out(s), "a|b\n1|x\n2|\n")
        self.assertEqual(out(s + ".mode csv\nselect * from t;\n"), "a|b\n1|x\n2|\na,b\r\n1,x\r\n2,\r\n")
        self.assertEqual(out(s + ".mode tabs\nselect * from t;\n"), "a|b\n1|x\n2|\na\tb\n1\tx\n2\t\n")
        self.assertEqual(out(s + ".mode line\nselect * from t;\n"), "a|b\n1|x\n2|\na = 1\nb = x\n\na = 2\nb = \n")
        self.assertEqual(out(s + ".mode column\nselect * from t;\n"), "a|b\n1|x\n2|\na  b\n-  -\n1  x\n2   \n")

    def test_csv_quoting(self):
        s = ".mode csv\nselect 'a,b', 'q\"r', 'plain', null;\n"
        self.assertEqual(out(s), '"a,b","q""r",plain,\r\n')

    def test_separator_nullvalue(self):
        self.assertEqual(out(".separator ;\nselect 1,2,null;\n.nullvalue NULL\nselect 1,null;\n"),
                         "1;2;\n1;NULL\n")

    def test_tables_schema(self):
        s = "create table b(x int);\ncreate table a(y text);\ncreate view v as select 1;\n.tables\n.schema a\n.schema\n"
        self.assertEqual(out(s), "a  b  v\nCREATE TABLE a(y text);\n"
                         "CREATE TABLE b(x int);\nCREATE TABLE a(y text);\nCREATE VIEW v as select 1;\n")


class Errors(unittest.TestCase):
    def test_continue_after_error(self):
        o, e, rc = run("select 1;\nselect * from nosuch;\nselect 2;\n")
        self.assertEqual(o, "1\n2\n")
        self.assertEqual(e, "Parse error near line 2: no such table: nosuch\n")
        self.assertEqual(rc, 1)

    def test_syntax_error(self):
        o, e, rc = run("select 1;\n\nselec 2;\nselect 3;\n")
        self.assertEqual(o, "1\n3\n")
        self.assertEqual(e, 'Parse error near line 3: near "selec": syntax error\n')
        self.assertEqual(rc, 1)

    def test_runtime_error(self):
        o, e, rc = run("create table t(a unique);\ninsert into t values(1);\ninsert into t values(1);\nselect 9;\n")
        self.assertEqual(o, "9\n")
        self.assertEqual(e, "Error near line 3: UNIQUE constraint failed: t.a\n")
        self.assertEqual(rc, 1)

    def test_clean_exit(self):
        self.assertEqual(run("select 1;\n")[2], 0)

    def test_double_quoted_is_identifier(self):
        o, e, rc = run('select "abc";\n')
        self.assertEqual(o, "")
        self.assertIn('no such column: abc', e)
        self.assertEqual(rc, 1)
        self.assertEqual(out('create table t("a b" int);\ninsert into t values(5);\nselect "a b" from t;\n'), "5\n")

    def test_multiline_statement_line_number(self):
        o, e, rc = run("select 1;\nselect\n  nosuch\n  from t;\n")
        self.assertEqual(e, "Parse error near line 2: no such table: t\n")

    def test_unknown_dot_command(self):
        o, e, rc = run(".bogus\nselect 1;\n")
        self.assertEqual(o, "1\n")
        self.assertEqual(rc, 1)

    def test_last_statement_without_semicolon(self):
        self.assertEqual(out("select 5"), "5\n")

    def test_semicolon_in_string_and_comment(self):
        self.assertEqual(out("select 'a;b'; -- x; y\nselect 2 /* ; */;\n"), "a;b\n2\n")


class DDLDML(unittest.TestCase):
    def test_rowid_alias_and_autoassign(self):
        s = "create table t(id integer primary key, v text);\ninsert into t(v) values('a'),('b');\n" \
            "insert into t values(10,'c');\ninsert into t(v) values('d');\nselect id, v, rowid from t;\n"
        self.assertEqual(out(s), "1|a|1\n2|b|2\n10|c|10\n11|d|11\n")

    def test_defaults_and_default_values(self):
        s = "create table t(a int default 5, b text default 'x', c default (1+2));\ninsert into t default values;\n" \
            "insert into t(a) values(9);\nselect * from t;\n"
        self.assertEqual(out(s), "5|x|3\n9|x|3\n")

    def test_constraint_messages(self):
        s = "create table t(a integer not null, b int check(b>0), c unique);\n" \
            "insert into t values(null,1,1);\ninsert into t values(1,0,1);\ninsert into t values(1,1,1);\n" \
            "insert into t values(2,1,1);\n"
        o, e, rc = run(s)
        self.assertEqual(e.splitlines(), [
            "Error near line 2: NOT NULL constraint failed: t.a",
            "Error near line 3: CHECK constraint failed: b>0",
            "Error near line 5: UNIQUE constraint failed: t.c"])

    def test_insert_or(self):
        s = "create table t(a int primary key, b);\ninsert into t values(1,'x');\n" \
            "insert or ignore into t values(1,'y');\ninsert or replace into t values(1,'z');\n" \
            "replace into t values(2,'w');\nselect * from t order by a;\nselect changes();\n"
        self.assertEqual(out(s), "1|z\n2|w\n1\n")

    def test_multirow_insert_statement_atomic(self):
        s = "create table t(a int primary key);\ninsert into t values(1);\ninsert into t values(2),(3),(1);\nselect * from t;\n"
        o, e, rc = run(s)
        self.assertEqual(o, "1\n")

    def test_update_delete_changes(self):
        s = "create table t(a);\ninsert into t values(1),(2),(3);\nupdate t set a=a*10 where a>1;\nselect changes();\n" \
            "delete from t where a=1;\nselect changes(), total_changes(), last_insert_rowid();\nselect * from t;\n"
        self.assertEqual(out(s), "2\n1|6|3\n20\n30\n")

    def test_insert_select_and_returning(self):
        s = "create table t(a, b);\ninsert into t values(1,2);\ninsert into t select b, a from t;\n" \
            "insert into t(a) values(7) returning a, b, rowid;\nselect * from t;\n"
        self.assertEqual(out(s), "7||3\n1|2\n2|1\n7|\n")

    def test_create_if_not_exists_and_drop(self):
        s = "create table t(a);\ncreate table if not exists t(b);\ndrop table t;\ndrop table if exists t;\ndrop table t;\n"
        o, e, rc = run(s)
        self.assertEqual(e, "Parse error near line 5: no such table: t\n")

    def test_affinity_storage(self):
        s = "create table t(i integer, r real, x text, n numeric, b);\n" \
            "insert into t values('12', 5, 5, '3.0', '7');\nselect typeof(i), typeof(r), typeof(x), typeof(n), typeof(b) from t;\n" \
            "select i, r, x, n, b from t;\n"
        self.assertEqual(out(s), "integer|real|text|integer|text\n12|5.0|5|3|7\n")

    def test_integer_pk_datatype_mismatch(self):
        o, e, rc = run("create table t(id integer primary key);\ninsert into t values('abc');\n")
        self.assertIn('datatype mismatch', e)

    def test_sqlite_master(self):
        s = "create table t(a int, b text);\ncreate index i on t(a);\nselect type, name, tbl_name, sql from sqlite_master;\n"
        self.assertEqual(out(s), "table|t|t|CREATE TABLE t(a int, b text)\nindex|i|t|CREATE INDEX i on t(a)\n")


class Expressions(unittest.TestCase):
    def q(self, e):
        return out("select %s;\n" % e).rstrip('\n')

    def test_arith(self):
        self.assertEqual(self.q("7/2, -7/2, 7%3, -7%3, 7.0/2, 7/0, 7%0, 1+2*3"), "3|-3|1|-1|3.5|||7")

    def test_overflow(self):
        self.assertEqual(self.q("9223372036854775807+1, 9223372036854775807*2, -9223372036854775808"),
                         "9.2233720368547758e+18|1.8446744073709552e+19|-9223372036854775808")

    def test_typeof(self):
        self.assertEqual(self.q("typeof(1), typeof(1.0), typeof('a'), typeof(x'00'), typeof(null), typeof(1+1.0)"),
                         "integer|real|text|blob|null|real")

    def test_comparison(self):
        self.assertEqual(self.q("1=1.0, '1'=1, 'a'<'B', 5<'a', x'00'>'zzz', null=null, null is null, 1 is not null"),
                         "1|0|0|1|1||1|1")

    def test_three_valued(self):
        self.assertEqual(self.q("null and 0, null and 1, null or 1, null or 0, not null, 1 and 1"), "0||1|||1")

    def test_in_between_like_glob(self):
        self.assertEqual(self.q("2 in (1,2,3), 5 in (1,2), 5 in (1,null), 5 not in (1,2), 3 between 1 and 5, 'abc' like 'A_C', 'abc' glob 'A*', 'abc' glob 'a[a-c]c'"),
                         "1|0||1|1|1|0|1")
        self.assertEqual(self.q("'50%' like '50\\%' escape '\\', 'a_b' like 'a\\_b' escape '\\', 'axb' like 'a\\_b' escape '\\'"), "1|1|0")

    def test_case_cast(self):
        self.assertEqual(self.q("case when 0 then 'a' when 1 then 'b' end, case 3 when 1 then 'x' else 'z' end, case 9 when 1 then 'x' end"), "b|z|")
        self.assertEqual(self.q("cast('12abc' as integer), cast(3.9 as integer), cast('3.5' as real), cast(5 as text), cast('1e2' as numeric), cast(null as integer)"),
                         "12|3|3.5|5|100|")

    def test_concat_blob(self):
        self.assertEqual(self.q("'a'||1||2.5, x'4142', hex(x'4142'), length(x'4142'), typeof(x'41'||'b'), 'a'||null"), "a12.5|AB|4142|2|text|")

    def test_collation(self):
        s = "create table t(a text collate nocase, b);\ninsert into t values('B','x'),('a','x'),('C','x');\n" \
            "select a from t order by a;\nselect a from t order by b, a collate binary;\nselect 'a' = 'A' collate nocase;\n" \
            "select a from t where a = 'b';\n"
        self.assertEqual(out(s), "a\nB\nC\nB\nC\na\n1\nB\n")

    def test_functions(self):
        self.assertEqual(self.q("abs(-5), abs(-2.5), abs(null), upper('ab'), lower('AB'), length('héllo'), length(12345)"), "5|2.5||AB|ab|5|5")
        self.assertEqual(self.q("substr('hello',2,3), substr('hello',-3), substr('hello',0,3), substr('hello',2), substring('hello',1,2)"), "ell|llo|he|ello|he")
        self.assertEqual(self.q("instr('hello','ll'), instr('a','z'), replace('aaa','a','bb'), trim('  x  '), ltrim('xxy','x'), rtrim('yxx','x'), trim('abcba','ab')"), "3|0|bbbbbb|x|y|y|c")
        self.assertEqual(self.q("coalesce(null,null,3), ifnull(null,'d'), nullif(1,1), nullif(1,2), iif(1>2,'a','b'), max(1,5,3), min('b','a'), max(1,null)"), "3|d||1|b|5|a|")
        self.assertEqual(self.q("sign(-3), sign(0), sign(2.5), round(2.5), round(-2.5), round(2.567,1), round(5), char(72,105), unicode('A')"), "-1|0|1|3.0|-3.0|2.6|5.0|Hi|65")
        self.assertEqual(self.q("hex('abc'), quote('it''s'), quote(1.5), quote(null), quote(x'0a'), typeof(zeroblob(3)), length(zeroblob(3))"), "616263|'it''s'|1.5|NULL|X'0A'|blob|3")
        self.assertEqual(self.q("typeof(random()), length(randomblob(8)), like('a%','abc'), glob('a*','abc')"), "integer|8|1|1")

    def test_printf(self):
        self.assertEqual(self.q("printf('%d|%5d|%-5d|%05d|%+d', 42, 42, 42, 42, 42)"), "42|   42|42   |00042|+42")
        self.assertEqual(self.q("printf('%.2f|%8.3f|%e|%g', 3.14159, 3.14159, 12345.678, 0.0001)"), "3.14|   3.142|1.234568e+04|0.0001")
        self.assertEqual(self.q("printf('%s|%10s|%-10s|%.2s|%c|%%|%x|%X|%o', 'abc','abc','abc','abc','xyz',255,255,8)"), "abc|       abc|abc       |ab|x|%|ff|FF|10")
        self.assertEqual(self.q("format('%q|%Q|%Q', 'it''s', 'it''s', null)"), "it''s|'it''s'|NULL")

    def test_aggregates(self):
        s = "create table t(g, v);\ninsert into t values('a',1),('a',2),('b',null),('b',4.5);\n" \
            "select g, count(*), count(v), sum(v), total(v), avg(v), min(v), max(v), group_concat(v) from t group by g;\n" \
            "select count(*), sum(v), total(v), avg(v), max(v) from t where 0;\nselect count(distinct g), sum(distinct v) from t;\n"
        self.assertEqual(out(s), "a|2|2|3|3.0|1.5|1|2|1,2\nb|2|1|4.5|4.5|4.5|4.5|4.5|4.5\n0||0.0||\n2|7.5\n")

    def test_order_by_variants(self):
        s = "create table t(a,b);\ninsert into t values(2,'x'),(1,'y'),(null,'z'),(3,'w');\n" \
            "select a from t order by a;\nselect a from t order by a desc;\nselect a from t order by a nulls last;\n" \
            "select b from t order by 1 desc limit 2;\nselect b, a*2 as d from t order by d desc limit 1 offset 1;\n"
        self.assertEqual(out(s), "\n1\n2\n3\n3\n2\n1\n\n1\n2\n3\n\nz\ny\nx|4\n")

    def test_limit_syntaxes(self):
        s = "create table t(a);\ninsert into t values(1),(2),(3),(4);\nselect a from t limit 2 offset 1;\nselect a from t limit 1,2;\nselect a from t limit -1 offset 3;\n"
        self.assertEqual(out(s), "2\n3\n2\n3\n4\n")


class Queries(unittest.TestCase):
    def test_join_group_having_subquery(self):
        s = ("create table d(id integer primary key, name);\ncreate table e(id integer primary key, d int, sal);\n"
             "insert into d values(1,'eng'),(2,'ops'),(3,'hr');\n"
             "insert into e values(1,1,10),(2,1,20),(3,2,5);\n"
             "select d.name, count(e.id), sum(e.sal) from d left join e on e.d = d.id group by d.name order by d.name;\n"
             "select name from d where exists (select 1 from e where e.d = d.id) order by name;\n"
             "select name from d where id in (select d from e) order by 1;\n"
             "select d, sum(sal) from e group by d having sum(sal) > 10;\n"
             "select (select count(*) from e where e.d = d.id) as n, name from d order by n desc, name;\n"
             "select name from (select * from d where id > 1) order by name desc;\n")
        self.assertEqual(out(s), "eng|2|30\nhr|0|\nops|1|5\neng\nops\neng\nops\n1|30\n2|eng\n1|ops\n0|hr\nops\nhr\n")

    def test_star_and_alias_names(self):
        s = ".headers on\nselect 1+1, 2 as x, 'a' || 'b';\n"
        self.assertEqual(out(s), "1+1|x|'a' || 'b'\n2|2|ab\n")

    def test_distinct(self):
        s = "create table t(a,b);\ninsert into t values(1,1),(1,1),(1,2),(null,1),(null,1);\nselect distinct a, b from t order by a, b;\nselect count(distinct a) from t;\n"
        self.assertEqual(out(s), "|1\n1|1\n1|2\n1\n")


if __name__ == '__main__':
    unittest.main()
