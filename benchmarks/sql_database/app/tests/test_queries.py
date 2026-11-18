import unittest
from tests.helpers import run, out

AB = ("create table a(id int, x text);\ncreate table b(id int, y text);\n"
      "insert into a values(1,'a1'),(2,'a2'),(3,'a3');\ninsert into b values(2,'b2'),(3,'b3'),(4,'b4');\n")


class Joins(unittest.TestCase):
    def test_inner(self):
        self.assertEqual(out(AB + "select * from a join b on a.id=b.id;\nselect * from a inner join b on a.id=b.id;\n"),
                         "2|a2|2|b2\n3|a3|3|b3\n" * 2)

    def test_left(self):
        self.assertEqual(out(AB + "select * from a left outer join b on a.id=b.id;\n"),
                         "1|a1||\n2|a2|2|b2\n3|a3|3|b3\n")

    def test_left_on_vs_where(self):
        self.assertEqual(out(AB + "select a.id, y from a left join b on a.id=b.id and b.y='b3';\n"), "1|\n2|\n3|b3\n")
        self.assertEqual(out(AB + "select a.id, y from a left join b on a.id=b.id where b.id is null;\n"), "1|\n")

    def test_right_full(self):
        self.assertEqual(out(AB + "select * from a right join b on a.id=b.id;\n"),
                         "2|a2|2|b2\n3|a3|3|b3\n||4|b4\n")
        self.assertEqual(out(AB + "select * from a full outer join b on a.id=b.id;\n"),
                         "1|a1||\n2|a2|2|b2\n3|a3|3|b3\n||4|b4\n")

    def test_cross_and_comma(self):
        self.assertEqual(out(AB + "select count(*) from a cross join b;\nselect count(*) from a, b where a.id < b.id;\n"), "9\n6\n")

    def test_natural_using(self):
        self.assertEqual(out(AB + "select * from a natural join b;\n"), "2|a2|b2\n3|a3|b3\n")
        self.assertEqual(out(AB + "select * from a join b using(id);\n"), "2|a2|b2\n3|a3|b3\n")
        self.assertEqual(out(AB + "select id, x, y from a join b using (id) where id > 2;\n"), "3|a3|b3\n")
        self.assertEqual(out(AB + "select a.id, b.id from a join b using (id);\n"), "2|2\n3|3\n")

    def test_ambiguous_and_missing(self):
        o, e, rc = run(AB + "select id from a, b;\n")
        self.assertEqual(e, "Parse error near line 5: ambiguous column name: id\n")
        o, e, rc = run(AB + "select a.zzz from a;\n")
        self.assertIn("no such column: a.zzz", e)

    def test_self_join_alias_three_way(self):
        s = AB + "create table c(id int, z text);\ninsert into c values(3,'c3');\n" \
            "select a.x, b.y, c.z from a join b on a.id=b.id join c on c.id=b.id;\n" \
            "select p.id, q.id from a p join a q on q.id = p.id + 1 order by 1;\n"
        self.assertEqual(out(s), "a3|b3|c3\n1|2\n2|3\n")

    def test_index_assisted_join_matches_scan(self):
        s = AB + "create index ib on b(id);\nselect * from a join b on a.id=b.id order by a.id;\n" \
            "select count(*) from a join b on b.id = a.id + 0;\n"
        self.assertEqual(out(s), "2|a2|2|b2\n3|a3|3|b3\n2\n")

    def test_affinity_in_join_condition(self):
        s = "create table p(a integer);\ncreate table q(b text);\ninsert into p values(1),(2);\ninsert into q values('1'),('x');\n" \
            "select a, b from p join q on a = b;\n"
        self.assertEqual(out(s), "1|1\n")


class Subqueries(unittest.TestCase):
    def test_scalar_in_exists(self):
        s = AB + "select (select max(id) from b);\nselect x from a where id in (select id from b);\n" \
            "select x from a where id not in (select id from b);\nselect x from a where exists (select 1 from b where b.id = a.id + 1);\n" \
            "select x from a where not exists (select 1 from b where b.id = a.id);\n"
        self.assertEqual(out(s), "4\na2\na3\na1\na1\na2\na3\na1\n")

    def test_scalar_empty_is_null_and_multi_row_first(self):
        self.assertEqual(out(AB + "select (select id from b where id > 100), (select id from b order by id desc);\n"), "|4\n")

    def test_correlated_in_select_list(self):
        self.assertEqual(out(AB + "select id, (select count(*) from b where b.id >= a.id) from a;\n"), "1|3\n2|3\n3|2\n")

    def test_in_null_semantics(self):
        s = "create table t(a);\ninsert into t values(1),(null);\n" \
            "select 5 in (select a from t), 1 in (select a from t), 5 not in (select a from t), null in (select a from t);\n" \
            "select 1 in (select a from t where 0), null in (select a from t where 0);\n"
        self.assertEqual(out(s), "|1||\n0|0\n")

    def test_from_subquery_and_alias(self):
        s = AB + "select d from (select id*2 as d from a) where d > 2;\nselect t.s from (select sum(id) as s from a) t;\n" \
            "select * from (select 1 as p, 2 as q) join (select 3 as r) on 1;\n"
        self.assertEqual(out(s), "4\n6\n6\n1|2|3\n")

    def test_multi_column_subquery_error(self):
        o, e, rc = run(AB + "select (select id, x from a);\n")
        self.assertIn("sub-select returns 2 columns - expected 1", e)

    def test_nested_correlation(self):
        s = AB + "select x from a where exists (select 1 from b where b.id = a.id and exists (select 1 from a a2 where a2.id = b.id and a2.id > 2));\n"
        self.assertEqual(out(s), "a3\n")


class Grouping(unittest.TestCase):
    def test_group_by_ordinal_alias_having(self):
        s = "create table t(g, v);\ninsert into t values('a',1),('b',5),('a',2),('c',7),('b',1);\n" \
            "select g, sum(v) from t group by 1 order by 1;\nselect g as k, count(*) from t group by k having count(*) > 1 order by k;\n" \
            "select g, sum(v) as s from t group by g having s > 4 order by s desc;\n"
        self.assertEqual(out(s), "a|3\nb|6\nc|7\na|2\nb|2\nc|7\nb|6\n")

    def test_groups_come_out_sorted(self):
        s = "create table t(g);\ninsert into t values('b'),('c'),('a'),('b');\nselect g, count(*) from t group by g;\n"
        self.assertEqual(out(s), "a|1\nb|2\nc|1\n")

    def test_bare_column_with_min_max(self):
        s = "create table t(n, v);\ninsert into t values('x',3),('y',1),('z',2);\nselect n, min(v) from t;\nselect n, max(v) from t;\n"
        self.assertEqual(out(s), "y|1\nx|3\n")

    def test_aggregate_misuse(self):
        o, e, rc = run("create table t(a);\nselect * from t where count(*) > 1;\n")
        self.assertIn("misuse of aggregate function count()", e)

    def test_aggregates_edge(self):
        s = "create table t(a);\ninsert into t values(1),(2),(null),(2);\n" \
            "select count(*), count(a), count(distinct a), sum(a), total(a), avg(a), min(a), max(a), group_concat(a), group_concat(distinct a) from t;\n" \
            "select group_concat(a, ';') from t;\nselect sum(a), total(a), avg(a), min(a), count(*) from t where a > 10;\n"
        self.assertEqual(out(s), "4|3|2|5|5.0|1.66666666666667|1|2|1,2,2|1,2\n1;2;2\n|0.0|||0\n")

    def test_sum_types_and_overflow(self):
        s = "create table t(a);\ninsert into t values(1),(2.5);\nselect sum(a), typeof(sum(a)) from t;\n" \
            "create table u(a);\ninsert into u values(9223372036854775807),(1);\nselect sum(a) from u;\nselect total(a) from u;\n"
        o, e, rc = run(s)
        self.assertEqual(o, "3.5|real\n9.2233720368547758e+18\n")
        self.assertIn("integer overflow", e)

    def test_text_and_minmax_collation(self):
        s = "create table t(a text collate nocase);\ninsert into t values('b'),('A'),('c');\nselect min(a), max(a) from t;\n"
        self.assertEqual(out(s), "A|c\n")

    def test_filter_clause(self):
        s = "create table t(a);\ninsert into t values(1),(2),(3);\nselect count(*) filter (where a > 1), sum(a) filter (where a < 3) from t;\n"
        self.assertEqual(out(s), "2|3\n")


class OrderingCompound(unittest.TestCase):
    def test_nulls_ordering(self):
        s = "create table t(a);\ninsert into t values(2),(null),(1);\n" \
            "select a from t order by a nulls first;\nselect a from t order by a desc nulls last;\nselect a from t order by a desc;\n"
        self.assertEqual(out(s), "\n1\n2\n2\n1\n\n2\n1\n\n")

    def test_mixed_types_order(self):
        s = "create table t(a);\ninsert into t values('b'),(2),(x'01'),(null),(1.5),('a');\nselect typeof(a), a from t order by a;\n"
        self.assertEqual(out(s), "null|\nreal|1.5\ninteger|2\ntext|a\ntext|b\nblob|\x01\n")

    def test_order_by_expression_and_nocase(self):
        s = "create table t(a);\ninsert into t values('b'),('A'),('c'),('B');\nselect a from t order by a;\nselect a from t order by a collate nocase, a;\n" \
            "select a from t order by lower(a) desc, a;\n"
        self.assertEqual(out(s), "A\nB\nb\nc\nA\nB\nb\nc\nc\nB\nb\nA\n")

    def test_union_intersect_except(self):
        self.assertEqual(out(AB + "select id from a union select id from b;\n"), "1\n2\n3\n4\n")
        self.assertEqual(out(AB + "select id from a union all select id from b;\n"), "1\n2\n3\n2\n3\n4\n")
        self.assertEqual(out(AB + "select id from a intersect select id from b;\n"), "2\n3\n")
        self.assertEqual(out(AB + "select id from a except select id from b;\n"), "1\n")
        self.assertEqual(out(AB + "select id from a union select id from b order by id desc limit 2;\n"), "4\n3\n")
        self.assertEqual(out("select 1 union select 2 union select 1;\n"), "1\n2\n")
        self.assertEqual(out("select 1, 'a' union all select 2, 'b' order by 1 desc;\n"), "2|b\n1|a\n")

    def test_compound_errors(self):
        o, e, rc = run("select 1, 2 union select 3;\n")
        self.assertIn("do not have the same number of result columns", e)
        o, e, rc = run("select 1 as a union select 2 order by zz;\n")
        self.assertIn("ORDER BY term does not match any column", e)

    def test_values_clause(self):
        self.assertEqual(out("values (1,'x'),(2,'y');\nvalues (3) union values (1);\n"), "1|x\n2|y\n1\n3\n")

    def test_limit_expressions(self):
        s = "create table t(a);\ninsert into t values(1),(2),(3),(4),(5);\nselect a from t order by a limit (select 2) offset 1+1;\nselect a from t limit 0;\n"
        self.assertEqual(out(s), "3\n4\n")


class CTEs(unittest.TestCase):
    def test_simple_and_multiple(self):
        s = AB + "with t as (select id from a) select * from t where id > 1;\nwith t(q) as (select 5), u as (select q*2 as z from t) select z from u;\n"
        self.assertEqual(out(s), "2\n3\n10\n")

    def test_recursive_counter_and_limit(self):
        self.assertEqual(out("with recursive c(n) as (select 1 union all select n+1 from c where n<5) select group_concat(n) from c;\n"), "1,2,3,4,5\n")
        self.assertEqual(out("with recursive c(n) as (select 1 union all select n+1 from c) select n from c limit 3;\n"), "1\n2\n3\n")

    def test_recursive_union_dedup_and_tree(self):
        s = ("create table e(id, boss);\ninsert into e values(1,null),(2,1),(3,1),(4,2);\n"
             "with recursive t(id, depth) as (select id, 0 from e where boss is null union all select e.id, t.depth+1 from e join t on e.boss = t.id) "
             "select id, depth from t order by depth, id;\n"
             "with recursive r(x) as (select 1 union select (x % 3) + 1 from r) select x from r order by x;\n")
        self.assertEqual(out(s), "1|0\n2|1\n3|1\n4|2\n1\n2\n3\n")

    def test_fibonacci(self):
        s = "with recursive f(a,b) as (select 0,1 union all select b,a+b from f where a<50) select group_concat(a) from f;\n"
        self.assertEqual(out(s), "0,1,1,2,3,5,8,13,21,34,55\n")

    def test_cte_in_insert_and_subquery(self):
        s = "create table t(a);\nwith c(n) as (values(1),(2)) insert into t select n from c;\nselect * from t;\n" \
            "select (with c(n) as (select 7) select n from c);\n"
        self.assertEqual(out(s), "1\n2\n7\n")


class Views(unittest.TestCase):
    def test_view_basic(self):
        s = AB + "create view v as select a.id, y from a join b on a.id=b.id;\nselect * from v where id=2;\n" \
            "create view w(p, q) as select id, x from a;\nselect q from w where p = 3;\n.tables\n.schema v\n" \
            "drop view v;\nselect * from v;\n"
        o, e, rc = run(s)
        self.assertEqual(o, "2|b2\na3\na  b  v  w\nCREATE VIEW v as select a.id, y from a join b on a.id=b.id;\n")
        self.assertIn("no such table: v", e)

    def test_view_if_not_exists_and_errors(self):
        o, e, rc = run("create view v as select 1;\ncreate view v as select 2;\ncreate view if not exists v as select 3;\nselect * from v;\ninsert into v values(1);\n")
        self.assertEqual(o, "1\n")
        self.assertIn("view v already exists", e)
        self.assertIn("cannot modify v because it is a view", e)

    def test_view_over_view_and_aggregate(self):
        s = AB + "create view v1 as select id from a;\ncreate view v2 as select count(*) as n from v1;\nselect n from v2;\n"
        self.assertEqual(out(s), "3\n")

    def test_drop_index_and_create_index(self):
        s = AB + "create index i on a(id);\ncreate unique index j on b(id);\ninsert into b values(2,'dup');\ndrop index i;\ndrop index if exists i;\nselect count(*) from a where id = 2;\n"
        o, e, rc = run(s)
        self.assertEqual(o, "1\n")
        self.assertIn("UNIQUE constraint failed: b.id", e)


class Windows(unittest.TestCase):
    E = ("create table e(id integer primary key, dept text, sal int);\n"
         "insert into e(dept,sal) values('a',10),('a',20),('a',20),('b',5),('b',7),('c',1);\n")

    def test_ranking(self):
        s = self.E + "select id, row_number() over (partition by dept order by sal), rank() over (partition by dept order by sal), dense_rank() over (partition by dept order by sal) from e;\n"
        self.assertEqual(out(s), "1|1|1|1\n2|2|2|2\n3|3|2|2\n4|1|1|1\n5|2|2|2\n6|1|1|1\n")

    def test_lag_lead_running_sum(self):
        s = self.E + "select id, sum(sal) over (order by id), lag(sal) over (order by id), lead(sal,2,-1) over (order by id) from e;\n"
        self.assertEqual(out(s), "1|10||20\n2|30|10|5\n3|50|20|7\n4|55|20|1\n5|62|5|-1\n6|63|7|-1\n")

    def test_first_last_nth_ntile(self):
        s = self.E + "select id, first_value(sal) over (partition by dept order by id), last_value(sal) over (partition by dept order by id), ntile(4) over (order by id), nth_value(sal,2) over (order by id) from e;\n"
        self.assertEqual(out(s), "1|10|10|1|\n2|10|20|1|20\n3|10|20|2|20\n4|5|5|2|20\n5|5|7|3|20\n6|1|1|4|20\n")

    def test_frames(self):
        s = self.E + "select id, sum(sal) over (order by id rows between 1 preceding and 1 following), " \
            "sum(sal) over (order by id rows between unbounded preceding and current row), " \
            "count(*) over (order by sal groups between 1 preceding and current row), count(*) over () from e order by id;\n"
        self.assertEqual(out(s), "1|30|10|2|6\n2|50|30|3|6\n3|45|50|3|6\n4|32|55|2|6\n5|13|62|2|6\n6|8|63|1|6\n")

    def test_range_offset_and_exclude(self):
        s = self.E + "select id, sum(sal) over (order by sal range between 5 preceding and current row), " \
            "sum(sal) over (order by id rows between 1 preceding and 1 following exclude current row) from e order by id;\n"
        self.assertEqual(out(s), "1|22|20\n2|40|30\n3|40|25\n4|6|27\n5|12|6\n6|1|7\n")

    def test_percent_cume(self):
        s = "create table t(a);\ninsert into t values(1),(2),(2),(4);\nselect a, percent_rank() over (order by a), cume_dist() over (order by a) from t;\n"
        self.assertEqual(out(s), "1|0.0|0.25\n2|0.333333333333333|0.75\n2|0.333333333333333|0.75\n4|1.0|1.0\n")

    def test_named_window_and_aggregate_query(self):
        s = self.E + "select dept, sum(sal), rank() over (order by sum(sal) desc) from e group by dept;\n" \
            "select id, sum(sal) over w from e where id < 3 window w as (order by id rows unbounded preceding);\n"
        self.assertEqual(out(s), "a|50|1\nb|12|2\nc|1|3\n1|10\n2|30\n")

    def test_window_with_order_by_outer(self):
        s = self.E + "select id, row_number() over (order by sal desc, id) as rn from e order by id desc limit 2;\n"
        self.assertEqual(out(s), "6|6\n5|4\n")

    def test_misuse(self):
        o, e, rc = run("select row_number() over (), 1 where row_number() over () = 1;\n")
        self.assertEqual(rc, 1)


if __name__ == '__main__':
    unittest.main()
