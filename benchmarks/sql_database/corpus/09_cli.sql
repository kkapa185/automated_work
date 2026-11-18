CREATE TABLE p(id INTEGER, name TEXT, score REAL);
INSERT INTO p VALUES (1, 'x y', 1.5), (2, 'has,comma', NULL), (3, 'q"uote', 2);
SELECT * FROM p;
.headers on
SELECT * FROM p;
.mode csv
SELECT * FROM p;
.headers off
.mode list
.separator :
SELECT * FROM p;
.separator |
.tables
.schema p
.nullvalue NULL
SELECT * FROM p WHERE score IS NULL;
