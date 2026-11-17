PROGRAM Main;
VAR x, y : INTEGER;
    z : REAL;

PROCEDURE Beta(c : INTEGER);
BEGIN
   c := c + 1;
END;

PROCEDURE Alpha(a : INTEGER; b : REAL);
VAR t : INTEGER;
BEGIN
   t := a * 2;
   Beta(t);
END;

BEGIN { Main }
   x := 7; y := x DIV 2; z := x / 2;
   Alpha(x + y, z);
END.
