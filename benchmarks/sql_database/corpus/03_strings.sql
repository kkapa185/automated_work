SELECT length('héllo'), upper('abc'), lower('ABC'), substr('hello world', 7), substr('hello', 2, 3), substr('hello', -3);
SELECT instr('hello', 'll'), replace('a-b-c', '-', '+'), trim('  x  '), ltrim('xxay', 'x'), rtrim('ayxx', 'x'), 'a' || 'b' || NULL;
SELECT printf('%5d|%-5s|%.2f|%x|%05.1f|%s', 42, 'ab', 3.14159, 255, 2.5, NULL), quote('it''s'), quote(NULL), quote(12), hex('AB'), unicode('A'), char(72, 105);
SELECT 'Hello' LIKE 'hello', 'Hello' GLOB 'hello', 'Hello' GLOB 'H*', 'abc' LIKE '_b%', 'a%c' LIKE 'a\%c' ESCAPE '\';
SELECT group_concat(x), group_concat(x, ';') FROM (SELECT 'a' AS x UNION ALL SELECT 'b' UNION ALL SELECT NULL UNION ALL SELECT 'c');
SELECT CASE WHEN 1 > 2 THEN 'x' WHEN 2 > 1 THEN 'y' ELSE 'z' END, CASE 3 WHEN 1 THEN 'one' WHEN 3 THEN 'three' END, CASE WHEN 0 THEN 1 END;
SELECT iif(1, 'yes', 'no'), format('%d-%s', 7, 'x'), length(NULL), length(123), lower(NULL) IS NULL;
