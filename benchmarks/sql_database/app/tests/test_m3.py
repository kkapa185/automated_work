import os
import shutil
import tempfile
import unittest
from tests.helpers import run, out


class Tx(unittest.TestCase):
    def test_commit_rollback(self):
        s = "create table t(a);\nbegin;\ninsert into t values(1);\nrollback;\nselect count(*) from t;\n" \
            "begin transaction;\ninsert into t values(2);\ncommit;\nselect * from t;\nbegin immediate;\ninsert into t values(3);\nend;\n" \
            "begin exclusive transaction;\ndelete from t;\nrollback transaction;\nselect count(*) from t;\n"
        self.assertEqual(out(s), "0\n2\n2\n")

    def test_ddl_rolls_back(self):
        s = "create table t(a);\nbegin;\ncreate table u(b);\ndrop table t;\nalter table u rename to w;\nrollback;\n.tables\n"
        self.assertEqual(out(s), "t\n")

    def test_transaction_errors(self):
        o, e, rc = run("commit;\nrollback;\nbegin;\nbegin;\ncommit;\n")
        self.assertEqual(e.splitlines(), ["Error near line 1: cannot commit - no transaction is active",
                                          "Error near line 2: cannot rollback - no transaction is active",
                                          "Error near line 4: cannot start a transaction within a transaction"])

    def test_error_in_txn_keeps_txn_open(self):
        s = "create table t(a unique);\nbegin;\ninsert into t values(1);\ninsert into t values(1);\ninsert into t values(2);\ncommit;\nselect * from t;\n"
        o, e, rc = run(s)
        self.assertEqual(o, "1\n2\n")
        self.assertEqual(rc, 1)

    def test_savepoints(self):
        s = ("create table t(a);\nbegin;\ninsert into t values(1);\nsavepoint s1;\ninsert into t values(2);\nsavepoint s2;\n"
             "insert into t values(3);\nrollback to s2;\nselect group_concat(a) from t;\nrollback to savepoint s1;\n"
             "select group_concat(a) from t;\nrelease s1;\ncommit;\nselect group_concat(a) from t;\n")
        self.assertEqual(out(s), "1,2\n1\n1\n")

    def test_savepoint_outside_txn_acts_as_txn(self):
        s = "create table t(a);\nsavepoint x;\ninsert into t values(1);\nrollback to x;\nrelease x;\nselect count(*) from t;\n" \
            "savepoint y;\ninsert into t values(5);\nrelease y;\nselect * from t;\nrollback;\n"
        o, e, rc = run(s)
        self.assertEqual(o, "0\n5\n")
        self.assertIn("cannot rollback - no transaction is active", e)

    def test_release_keeps_work_nested(self):
        s = "create table t(a);\nbegin;\nsavepoint a;\ninsert into t values(1);\nsavepoint b;\ninsert into t values(2);\nrelease a;\nrollback;\nselect count(*) from t;\n"
        self.assertEqual(out(s), "0\n")

    def test_unknown_savepoint(self):
        o, e, rc = run("begin;\nrollback to nope;\nrelease nope;\n")
        self.assertIn("no such savepoint: nope", e)

    def test_statement_atomicity(self):
        s = "create table t(a integer primary key, b int check(b < 10));\ninsert into t values(1,1),(2,2);\n" \
            "update t set b = b + 8;\nselect * from t;\ninsert into t values(5,1),(6,2),(1,3);\nselect count(*) from t;\n" \
            "update t set a = 2;\nselect * from t;\ndelete from t where 1/0;\nselect count(*) from t;\n"
        o, e, rc = run(s)
        self.assertEqual(o, "1|1\n2|2\n2\n1|1\n2|2\n2\n")

    def test_insert_or_rollback(self):
        s = "create table t(a unique);\ninsert into t values(1);\nbegin;\ninsert into t values(2);\ninsert or rollback into t values(1);\nselect count(*) from t;\ncommit;\n"
        o, e, rc = run(s)
        self.assertEqual(o, "1\n")
        self.assertIn("cannot commit - no transaction is active", e)


class Persistence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, 'x.db')

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_reopen(self):
        out("create table t(a integer primary key, b text, c real, d blob);\ninsert into t values(1,'héllo',2.5,x'00ff'),(2,null,-1e300,null),(9223372036854775807,'',0.0,x'');\n"
            "create index i on t(b);\ncreate view v as select a from t;\n", self.db)
        o = out("select a, b, c, hex(d), typeof(d) from t order by a;\nselect type, name from sqlite_master;\nselect count(*) from v;\n", self.db)
        self.assertEqual(o, "1|héllo|2.5|00FF|blob\n2||-1.0e+300||null\n9223372036854775807||0.0||blob\ntable|t\nindex|i\nview|v\n3\n")

    def test_rollback_not_persisted_commit_persisted(self):
        out("create table t(a);\nbegin;\ninsert into t values(1);\ncommit;\nbegin;\ninsert into t values(2);\nrollback;\n"
            "insert into t values(3);\nupdate t set a = a * 10;\ndelete from t where a = 10;\n", self.db)
        self.assertEqual(out("select * from t;\n", self.db), "30\n")

    def test_failed_statement_not_persisted(self):
        out("create table t(a unique);\ninsert into t values(1);\ninsert into t values(2),(1);\n", self.db)
        self.assertEqual(out("select * from t;\n", self.db), "1\n")

    def test_schema_changes_and_drop(self):
        out("create table t(a);\ncreate table u(b);\ninsert into u values(1);\ndrop table t;\nalter table u add column c default 7;\ncreate table autoinc(id integer primary key autoincrement, v);\n"
            "insert into autoinc(v) values('a'),('b');\ndelete from autoinc;\n", self.db)
        self.assertEqual(out(".tables\nselect * from u;\ninsert into autoinc(v) values('c');\nselect * from autoinc;\n", self.db),
                         "autoinc  u      \n1|7\n3|c\n")

    def test_user_version_and_many_commits(self):
        script = "create table t(a);\n" + "".join("insert into t values(%d);\n" % i for i in range(200)) + "pragma user_version = 42;\n"
        out(script, self.db)
        self.assertEqual(out("select count(*), sum(a) from t;\npragma user_version;\n", self.db), "200|19900\n42\n")

    def test_torn_tail_is_ignored(self):
        out("create table t(a);\ninsert into t values(1);\ninsert into t values(2);\n", self.db)
        size = os.path.getsize(self.db)
        with open(self.db, 'ab') as f:
            f.write(b'\x02\x40\x00\x00\x00\x00\x00\x00\x00partial-frame')
        self.assertEqual(out("select count(*) from t;\n", self.db), "2\n")
        out("insert into t values(3);\n", self.db)
        self.assertEqual(out("select count(*) from t;\n", self.db), "3\n")

    def test_truncated_last_commit(self):
        out("create table t(a);\ninsert into t values(1);\n", self.db)
        good = os.path.getsize(self.db)
        out("insert into t values(2);\n", self.db)
        with open(self.db, 'r+b') as f:
            f.truncate(os.path.getsize(self.db) - 3)
        self.assertEqual(out("select count(*) from t;\n", self.db), "1\n")
        self.assertEqual(os.path.getsize(self.db), good)

    def test_corrupted_crc_discards_frame(self):
        out("create table t(a);\ninsert into t values(1);\n", self.db)
        out("insert into t values(2);\n", self.db)
        with open(self.db, 'r+b') as f:
            f.seek(-1, 2)
            b = f.read(1)
            f.seek(-1, 2)
            f.write(bytes([b[0] ^ 0xff]))
        self.assertEqual(out("select count(*) from t;\n", self.db), "1\n")

    def test_not_a_database(self):
        with open(self.db, 'w') as f:
            f.write("hello world, definitely not a database file")
        o, e, rc = run("select 1;\n", self.db)
        self.assertEqual(rc, 1)
        self.assertIn("file is not a database", e)

    def test_stale_temp_file_ignored(self):
        out("create table t(a);\ninsert into t values(1);\n", self.db)
        with open(self.db + '.tmp-1', 'wb') as f:
            f.write(b'junk')
        self.assertEqual(out("select * from t;\ncreate table u(b);\n", self.db), "1\n")

    def test_new_file_not_created_for_reads(self):
        out("select 1;\n", self.db)
        self.assertFalse(os.path.exists(self.db))

    def test_memory_db_has_no_file(self):
        self.assertEqual(out("create table t(a);\ninsert into t values(1);\nselect * from t;\n"), "1\n")

    def test_unique_and_index_after_reload(self):
        out("create table t(a unique, b);\ncreate unique index ib on t(b);\ninsert into t values(1,1);\n", self.db)
        o, e, rc = run("insert into t values(1,2);\ninsert into t values(2,1);\nselect count(*) from t;\n", self.db)
        self.assertEqual(o, "1\n")
        self.assertIn("UNIQUE constraint failed: t.a", e)
        self.assertIn("UNIQUE constraint failed: t.b", e)


class SchemaTable(unittest.TestCase):
    def test_sqlite_master_rows(self):
        s = "create table t(a int primary key, b text unique);\ncreate index i on t(b);\ncreate view v as select 1;\n" \
            "select type, name, tbl_name, rootpage, sql from sqlite_master;\nselect count(*) from sqlite_schema;\n"
        self.assertEqual(out(s), "table|t|t|2|CREATE TABLE t(a int primary key, b text unique)\n"
                                 "index|sqlite_autoindex_t_1|t|3|\nindex|sqlite_autoindex_t_2|t|4|\n"
                                 "index|i|t|5|CREATE INDEX i on t(b)\nview|v|v|0|CREATE VIEW v as select 1\n5\n")

    def test_if_not_exists_stripped_from_sql(self):
        s = "create table if not exists t(a);\ncreate unique index if not exists i on t(a);\nselect sql from sqlite_master;\n"
        self.assertEqual(out(s), "CREATE TABLE t(a)\nCREATE UNIQUE INDEX i on t(a)\n")

    def test_cannot_modify_schema_table(self):
        o, e, rc = run("insert into sqlite_master values(1,2,3,4,5);\ndrop table sqlite_master;\ncreate table sqlite_x(a);\n")
        self.assertEqual(rc, 1)
        self.assertIn("object name reserved for internal use: sqlite_x", e)


class Alter(unittest.TestCase):
    def test_add_column(self):
        s = "create table t(a);\ninsert into t values(1),(2);\nalter table t add column b text default 'x';\nalter table t add c integer;\n" \
            "insert into t values(3,'y',9);\nselect * from t;\nselect sql from sqlite_master;\n"
        self.assertEqual(out(s), "1|x|\n2|x|\n3|y|9\nCREATE TABLE t(a, b text default 'x', c integer)\n")

    def test_add_column_errors(self):
        o, e, rc = run("create table t(a);\nalter table t add column a;\nalter table t add column p integer primary key;\n"
                       "alter table t add column u unique;\nalter table t add column n not null;\nalter table zz add column q;\n")
        self.assertEqual([l.split(': ', 1)[1] for l in e.splitlines()],
                         ["duplicate column name: a", "Cannot add a PRIMARY KEY column", "Cannot add a UNIQUE column",
                          "Cannot add a NOT NULL column with default value NULL", "no such table: zz"])

    def test_rename_table(self):
        s = "create table t(a integer primary key, b);\ncreate index ib on t(b);\ninsert into t(b) values('q');\nalter table t rename to u;\n" \
            "select * from u;\nselect * from t;\nselect name, tbl_name from sqlite_master;\ninsert into u(b) values('r');\nselect count(*) from u where b = 'r';\n"
        o, e, rc = run(s)
        self.assertEqual(o, "1|q\nu|u\nib|u\n1\n")
        self.assertIn("no such table: t", e)

    def test_rename_table_conflict(self):
        o, e, rc = run("create table t(a);\ncreate table u(a);\nalter table t rename to u;\n")
        self.assertIn("there is already another table or index with this name: u", e)

    def test_rename_column(self):
        s = "create table t(a, b check(b > 0));\ncreate index ia on t(a);\ncreate view v as select a from t;\ninsert into t values(1,2);\n" \
            "alter table t rename column a to z;\nselect z, b from t;\nselect * from v;\nselect sql from sqlite_master where name = 'ia';\n" \
            "insert into t values(1,0);\n"
        o, e, rc = run(s)
        self.assertEqual(o, "1|2\n1\nCREATE INDEX ia on t(\"z\")\n")
        self.assertIn("CHECK constraint failed: b > 0", e)

    def test_rename_column_errors(self):
        o, e, rc = run("create table t(a, b);\nalter table t rename column zz to y;\nalter table t rename column a to b;\n")
        self.assertEqual([l.split(': ', 1)[1] for l in e.splitlines()], ['no such column: "zz"', "duplicate column name: b"])

    def test_drop_column(self):
        s = "create table t(a, b, c);\ninsert into t values(1,2,3);\nalter table t drop column b;\nselect * from t;\nselect sql from sqlite_master;\n" \
            "alter table t drop column c;\nselect sql from sqlite_master;\nalter table t drop column a;\n"
        o, e, rc = run(s)
        self.assertEqual(o, "1|3\nCREATE TABLE t(a, c)\nCREATE TABLE t(a)\n")
        self.assertIn('cannot drop column "a": no other columns exist', e)


class Upsert(unittest.TestCase):
    T = "create table t(id integer primary key, n text unique, c int default 0);\ninsert into t values(1,'a',1),(2,'b',1);\n"

    def test_do_nothing(self):
        s = self.T + "insert into t values(1,'z',9) on conflict do nothing;\ninsert into t values(3,'a',9) on conflict(n) do nothing;\n" \
            "insert into t values(4,'d',9) on conflict do nothing;\nselect * from t order by id;\nselect changes();\n"
        self.assertEqual(out(s), "1|a|1\n2|b|1\n4|d|9\n1\n")

    def test_do_update(self):
        s = self.T + "insert into t values(1,'q',5) on conflict(id) do update set c = c + excluded.c, n = n || '!';\n" \
            "insert into t(n,c) values('b', 10) on conflict(n) do update set c = excluded.c where c < 5;\n" \
            "insert into t(n,c) values('b', 99) on conflict(n) do update set c = excluded.c where c < 5;\nselect * from t order by id;\n"
        self.assertEqual(out(s), "1|a!|6\n2|b|10\n")

    def test_target_mismatch_goes_to_error(self):
        o, e, rc = run(self.T + "insert into t values(5,'a',0) on conflict(id) do nothing;\n")
        self.assertIn("UNIQUE constraint failed: t.n", e)

    def test_upsert_multiple_rows_and_returning(self):
        s = self.T + "insert into t values(1,'x',1),(7,'y',2) on conflict(id) do update set c = 100 returning id, c;\n"
        self.assertEqual(out(s), "1|100\n7|2\n")


class Triggers(unittest.TestCase):
    def test_after_triggers_and_new_old(self):
        s = ("create table t(id integer primary key, a);\ncreate table log(m);\n"
             "create trigger i1 after insert on t begin insert into log values('i' || new.a); end;\n"
             "create trigger u1 after update of a on t begin insert into log values('u' || old.a || '>' || new.a); end;\n"
             "create trigger d1 after delete on t begin insert into log values('d' || old.a); end;\n"
             "insert into t(a) values('x'),('y');\nupdate t set a = 'z' where id = 1;\nupdate t set id = 5 where id = 2;\n"
             "delete from t where id = 1;\nselect * from log;\n")
        self.assertEqual(out(s), "ix\niy\nux>z\ndz\n")

    def test_before_raise_abort_and_ignore(self):
        s = ("create table t(a);\ncreate trigger b1 before insert on t when new.a < 0 begin select raise(abort, 'negative'); end;\n"
             "create trigger b2 before insert on t when new.a = 99 begin select raise(ignore); end;\n"
             "insert into t values(1);\ninsert into t values(-1);\ninsert into t values(99);\ninsert into t values(2),(-5),(3);\nselect * from t;\n")
        o, e, rc = run(s)
        self.assertEqual(o, "1\n")
        self.assertEqual(e.count("negative"), 2)

    def test_trigger_body_atomic_with_statement(self):
        s = ("create table t(a);\ncreate table u(b unique);\ninsert into u values(1);\n"
             "create trigger tr after insert on t begin insert into u values(new.a); end;\n"
             "insert into t values(2);\ninsert into t values(1);\nselect * from t order by a;\nselect * from u order by b;\n")
        o, e, rc = run(s)
        self.assertEqual(o, "2\n1\n2\n")
        self.assertIn("UNIQUE constraint failed: u.b", e)

    def test_when_clause_and_update_columns(self):
        s = ("create table t(a, b);\ncreate table log(m);\ncreate trigger tr after update of b on t when new.b > 5 begin insert into log values(new.b); end;\n"
             "insert into t values(1,1);\nupdate t set a = 10;\nupdate t set b = 3;\nupdate t set b = 8;\nselect * from log;\n")
        self.assertEqual(out(s), "8\n")

    def test_instead_of_on_view(self):
        s = ("create table t(a, b);\ncreate view v as select a, b from t;\n"
             "create trigger vi instead of insert on v begin insert into t values(new.a * 2, new.b); end;\n"
             "create trigger vd instead of delete on v begin delete from t where a = old.a; end;\n"
             "create trigger vu instead of update on v begin update t set b = new.b where a = old.a; end;\n"
             "insert into v values(1,'p'),(2,'q');\nupdate v set b = 'Q' where a = 4;\ndelete from v where a = 2;\nselect * from t;\n")
        self.assertEqual(out(s), "4|Q\n")

    def test_drop_trigger_and_table_drops_triggers(self):
        s = ("create table t(a);\ncreate table log(m);\ncreate trigger tr after insert on t begin insert into log values(1); end;\n"
             "insert into t values(1);\ndrop trigger tr;\ninsert into t values(2);\nselect count(*) from log;\n"
             "create trigger tr2 after insert on t begin insert into log values(1); end;\ndrop table t;\nselect name from sqlite_master where type = 'trigger';\n"
             "drop trigger if exists nope;\ndrop trigger nope;\n")
        o, e, rc = run(s)
        self.assertEqual(o, "1\n")
        self.assertIn("no such trigger: nope", e)

    def test_trigger_with_case_and_multiple_statements_in_shell(self):
        s = ("create table t(a);\ncreate table log(m);\ncreate trigger tr after insert on t\nbegin\n"
             "  insert into log values(case when new.a > 1 then 'big' else 'small' end);\n  insert into log values('second');\nend;\n"
             "insert into t values(5);\nselect * from log;\n")
        self.assertEqual(out(s), "big\nsecond\n")

    def test_trigger_persists(self):
        d = tempfile.mkdtemp()
        try:
            db = os.path.join(d, 't.db')
            out("create table t(a);\ncreate table log(m);\ncreate trigger tr after insert on t begin insert into log values(new.a); end;\ninsert into t values(1);\n", db)
            self.assertEqual(out("insert into t values(2);\nselect * from log;\n", db), "1\n2\n")
        finally:
            shutil.rmtree(d)


class Pragmas(unittest.TestCase):
    def test_table_info(self):
        s = "create table t(a integer primary key, b text not null default 'x', c);\npragma table_info(t);\n"
        self.assertEqual(out(s), "0|a|integer|0||1\n1|b|text|1|'x'|0\n2|c||0||0\n")

    def test_misc_pragmas_ignored_or_answered(self):
        self.assertEqual(out("pragma foreign_keys = on;\npragma integrity_check;\npragma user_version;\npragma bogus_thing;\n"), "ok\n0\n")


if __name__ == '__main__':
    unittest.main()
