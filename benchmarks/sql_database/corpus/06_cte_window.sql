WITH RECURSIVE cnt(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM cnt WHERE n < 10) SELECT group_concat(n) FROM cnt;
WITH RECURSIVE fib(a, b, i) AS (SELECT 0, 1, 1 UNION ALL SELECT b, a + b, i + 1 FROM fib WHERE i < 15) SELECT max(a) FROM fib;
CREATE TABLE sales(region TEXT, month INTEGER, amount INTEGER);
INSERT INTO sales VALUES ('n', 1, 10), ('n', 2, 30), ('n', 3, 20), ('s', 1, 5), ('s', 2, 5), ('s', 3, 50);
WITH t AS (SELECT region, sum(amount) s FROM sales GROUP BY region) SELECT * FROM t ORDER BY s DESC;
SELECT region, month, amount, sum(amount) OVER (PARTITION BY region ORDER BY month) FROM sales ORDER BY region, month;
SELECT region, month, row_number() OVER (ORDER BY amount DESC, region, month), rank() OVER (ORDER BY amount DESC) FROM sales ORDER BY region, month;
SELECT region, amount, lag(amount) OVER (PARTITION BY region ORDER BY month), lead(amount, 1, -1) OVER (PARTITION BY region ORDER BY month) FROM sales ORDER BY region, month;
SELECT region, avg(amount) OVER (PARTITION BY region), dense_rank() OVER (PARTITION BY region ORDER BY amount) FROM sales ORDER BY region, month;
