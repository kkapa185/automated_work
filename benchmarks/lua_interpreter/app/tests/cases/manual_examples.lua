-- R24: examples from docs/manual.of with their stated results
local function cerr(src) local f, e = load(src, "=c"); assert(not f); return e end
-- §3.1: the five literal strings denote the same string
local a1 = 'alo\n123"'
assert(a1 == "alo\n123\"" and a1 == '\97lo\10\04923"' and a1 == [[alo
123"]] and a1 == [==[
alo
123"]==])
-- §3.3.4 scoping example: prints 10, 12, 11, 10
local out = {}
local function print(...) out[#out + 1] = table.concat({...}, ",") end
do
  local env = setmetatable({print = print}, {__index = _G})
  local f = load([[
    global print, x
    x = 10
    do
      local x = x
      print(x)
      x = x + 1
      do
        local x = x + 1
        print(x)
      end
      print(x)
    end
    print(x)
  ]], "=scoping", "t", env)
  f()
end
assert(table.concat(out, " ") == "10 12 11 10")
-- §3.3.1 global default / void declaration example
assert(load("X = 1; do global Y; Y = 1 end; X = 2", "=c"))
assert(cerr("X = 1; do global Y; Y = 1; X = 1 end") == "c:1: variable 'X' not declared")
-- §3.3.3 closures: ten closures share x, each has its own y
do
  local acc = {}
  local x = 20
  for i = 1, 10 do local y = 0; acc[i] = function() y = y + 1; return x + y end end
  assert(acc[1]() == 21 and acc[1]() == 22 and acc[2]() == 21)
  x = 100; assert(acc[3]() == 101)
end
-- §3.3.3 multiple assignment: i, a[i] = i+1, 20 sets a[3] (i evaluated before assignment)
do local i, a = 3, {}; i, a[i] = i + 1, 20; assert(a[3] == 20 and a[4] == nil and i == 4) end
do local x, y, z = 1, 2, 3; x, y = y, x; assert(x == 2 and y == 1); x, y, z = y, z, x; assert(x == 1 and y == 3 and z == 2) end
-- §3.4.12 logical operators
assert((10 or 20) == 10 and (10 or error()) == 10 and (nil or "a") == "a" and (nil and 10) == nil)
assert((false and error()) == false and (false and nil) == false and (false or nil) == nil and (10 and 20) == 20)
-- §3.4.12 multires expressions
local function f() return 1, 2, 3 end
local function g() return "g1", "g2" end
local x, y, z
assert(select('#', f()) == 3 and select('#', (f())) == 1 and select('#', 0, f()) == 4 and select('#', f(), 0) == 2)
assert(1 + f() == 2)
x, y, z = 9, f(); assert(x == 9 and y == 1 and z == 2)
x, y, z = f(); assert(x == 1 and y == 2 and z == 3)
x, y, z = f(), g(); assert(x == 1 and y == "g1" and z == "g2")
x, y, z = (f()); assert(x == 1 and y == nil and z == nil)
assert(#{f()} == 3 and #{...} == 0 and #{f(), 5} == 2 and ({f(), 5})[2] == 5)
local function va(...) local a, b = ...; return a, b, ... end
local r = {va(7, 8, 9)}; assert(#r == 5 and r[1] == 7 and r[2] == 8 and r[3] == 7 and r[5] == 9)
-- §3.4.11 function definition sugar
do
  local t = {a = {b = {c = {}}}}
  function t.a.b.c.f(v) return v end
  function t.a.b.c:g(v) return self == t.a.b.c and v end
  assert(t.a.b.c.f(5) == 5 and t.a.b.c:g(6) == 6 and t.a.b.c.g(t.a.b.c, 7) == 7)
  local function rec(n) if n == 0 then return "r" end return rec(n - 1) end   -- local function f ... is  local f; f = function
  assert(rec(3) == "r")
end
-- §3.3.4 attributes: const and close, global declarations (manual examples)
assert(load("global X; global<const> *; print(math.pi); X = 1", "=c"))
assert(cerr("global X; global<const> *; print(math.pi); X = 1; Y = 1") == "c:1: attempt to assign to const variable 'Y'")
assert(cerr("global X <const>, _G; X = 1") == "c:1: attempt to assign to const variable 'X'")
assert(load("global X <const>, _G; _ENV.X = 1; _G.print(X)", "=c"))
-- global function: translates to  global f; global f = function ... end  (error if already defined)
assert(select(2, pcall(load("function ff() end; global function ff() end", "=c"))) == "c:1: global 'ff' already defined")
-- §3.3.8 to-be-closed: reverse order, value passed as first argument, no second argument without error
do
  local order, nargs = {}, {}
  local function mk(n) return setmetatable({}, {__close = function(...) order[#order + 1] = n; nargs[#nargs + 1] = select('#', ...) end}) end
  do local a <close> = mk("a"); local b <close> = mk("b"); local c <close> = mk("c") end
  assert(table.concat(order) == "cba" and nargs[1] == 1)
  local ok = pcall(function() local d <close> = mk("d"); error("x") end)
  assert(not ok and order[4] == "d" and nargs[4] == 2)
  -- nil and false are ignored; after an error the other pending closing methods still run
  do local n <close> = nil; local f <close> = false end
  order = {}
  local ok2, e2 = pcall(function()
    local p <close> = setmetatable({}, {__close = function() order[#order + 1] = "p" end})
    local q <close> = setmetatable({}, {__close = function() error("q failed", 0) end})
    return 1
  end)
  assert(not ok2 and e2 == "q failed" and order[1] == "p")
end
-- §3.3.5 for: generic for loop variables: only the first (control) variable is read-only
assert(load("for a, b in pairs({}) do b = 1 end", "=c"))
assert(cerr("for a, b in pairs({}) do a = 1 end") == "c:1: attempt to assign to const variable 'a'")
-- §3.3.5 numeric for: integer loop if start and step are integers, limit may be float; floats otherwise
do
  local n, last = 0
  for i = 1, 3.9 do n = n + 1; last = i end
  assert(n == 3 and math.type(last) == "integer")
  n = 0; for i = 1.0, 3 do n = n + 1; last = i end
  assert(n == 3 and math.type(last) == "float")
end
-- §6.4 string.gsub empty-match example: callbacks see positions (1,2) (3,3) (4,4)
do
  local seen = {}
  string.gsub("abc", "()a*()", function(p1, p2) seen[#seen + 1] = p1 .. " " .. p2 end)
  assert(seen[1] == "1 2" and seen[2] == "3 3" and seen[3] == "4 4" and #seen == 3)
end
-- §6.4 string.format('%q') example
assert(string.format('%q', 'a string with "quotes" and \n new line') == '"a string with \\"quotes\\" and \\\n new line"')
-- §6.4 gmatch examples
do
  local words = {}
  for w in string.gmatch("hello world from Lua", "%a+") do words[#words + 1] = w end
  assert(table.concat(words, "|") == "hello|world|from|Lua")
  local t = {}
  for k, v in string.gmatch("from=world, to=Lua", "(%w+)=(%w+)") do t[k] = v end
  assert(t.from == "world" and t.to == "Lua")
end
-- §3.4.1/§3.4.3 arithmetic and conversions
assert(7 // 2 == 3 and -7 // 2 == -4 and 7 % -3 == -2 and -7 % 3 == 2 and 7.5 // 2 == 3.0 and 2^2 == 4.0 and 1 / 2 == 0.5)
assert(3 | 4 == 7 and 7 & 2 == 2 and 5 ~ 3 == 6 and ~0 == -1 and 1 << 62 == 4611686018427387904 and 1 >> 1 == 0)
assert("10" + 5 == 15 and "3" * "4" == 12 and 10 .. 20 == "1020" and #"abc" == 3)
-- §3.4.7: the length of a table with a border
assert(#{10, 20, 30} == 3 and #{} == 0)
