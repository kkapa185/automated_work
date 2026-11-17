program Deep;
var r : integer;
procedure L1(a : integer);
   procedure L2(b : integer);
      procedure L3(c : integer);
      var d : integer;
      begin
         d := c * 3 - 1
      end;
   begin
      L3(b * 2)
   end;
begin
   L2(a + 1)
end;
begin
   r := 1;
   L1(r)
end.
