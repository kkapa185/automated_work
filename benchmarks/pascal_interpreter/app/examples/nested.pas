PROGRAM Main;
VAR x, y : INTEGER;
    z : REAL;

PROCEDURE Alpha(a : INTEGER; b : REAL);
VAR t : INTEGER;
    PROCEDURE Beta(c : INTEGER);
    VAR u : INTEGER;
    BEGIN { Beta }
       u := c * 2;
    END;  { Beta }
BEGIN { Alpha }
   t := a DIV 2 + 7;
   Beta(t);
END;  { Alpha }

BEGIN { Main }
   x := 10; y := -(3 + 4) * 2;
   z := x / 4;
   Alpha(x + y, z);
END.  { Main }
