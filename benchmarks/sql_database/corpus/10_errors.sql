SELECT * FROM missing_table;
SELECT nope FROM (SELECT 1 AS yes);
SELEC 1;
CREATE TABLE x(a); INSERT INTO x VALUES (1, 2);
SELECT 'after errors', count(*) FROM x;
SELECT abs('a'), abs(-9223372036854775807 - 1) IS NULL;
SELECT 1 FROM x WHERE a = (SELECT a FROM x UNION ALL SELECT 2);
SELECT 'still running';
