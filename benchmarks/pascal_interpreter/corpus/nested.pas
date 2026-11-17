program Nested;
var total : integer;

procedure Outer(n : integer);
var k : integer;

   procedure Inner(m, p : integer; f : real);
   var z : real;
   begin
      z := m * p + f;
      z := z + m DIV 2
   end;

begin
   k := n * 3;
   Inner(n + 1, k, 0.5);
   Inner(1, 2, 3.0)
end;

procedure Empty;
begin
end;

BEGIN {main}
   total := 10;
   Outer(total);
   Empty();
   Outer(2);
END.
