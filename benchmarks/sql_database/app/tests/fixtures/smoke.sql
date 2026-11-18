create table t(a integer primary key, b text);
insert into t(b) values('x'),('y');
select a, b, 1.0*a from t;
