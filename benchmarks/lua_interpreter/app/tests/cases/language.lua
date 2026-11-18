dofile("tests/cases/prelude.lua")
-- R7: statements
local a, b, c = 1, 2
eq(a, 1); eq(b, 2); eq(c, nil)
a, b = b, a; eq(a, 2); eq(b, 1)
local t = {}
local i = 1
i, t[i] = i + 1, 20      -- t[1] = 20 (index evaluated before assignment)
eq(t[1], 20); eq(i, 2)
local function mr() return 1, 2, 3 end
local x, y, z, w = mr(); eq(w, nil); eq(z, 3)
x, y = (mr()); eq(x, 1); eq(y, nil)
t = {mr(), mr()}; eq(#t, 4)
t = {mr(), (mr())}; eq(#t, 2)
t = {[1] = "a", "b"}; eq(t[1], "b")
t = {1, 2, nil, 4}; eq(t[4], 4)
eq(select('#', mr()), 3); eq(select('#', (mr())), 1); eq(select(2, mr()), 2); eq(select(-1, mr()), 3)
local function va(...) local n = select('#', ...); return n, ... end
eq(va(), 0); eq(select('#', va(nil, nil)), 3)
local function va2(...) local a, b = ...; return a, b end
local p, q = va2(7); eq(p, 7); eq(q, nil)
local function va3(...) return {...}, select('#', ...) end
local tt, nn = va3(1, nil, nil); eq(nn, 3)
-- while / repeat / break / goto
local n = 0
while true do n = n + 1; if n > 5 then break end end; eq(n, 6)
n = 0; repeat local k = n; n = n + 1 until k >= 3; eq(n, 4)
local s = ""
for i = 1, 5 do
  if i % 2 == 0 then goto continue end
  s = s .. i
  ::continue::
end
eq(s, "135")
s = ""
for i = 1, 3 do for j = 1, 3 do
  if j == 2 then goto next_i end
  s = s .. i .. j .. ","
end ::next_i:: end
eq(s, "11,21,31,")
do local k = 0; ::top:: k = k + 1; if k < 5 then goto top end; eq(k, 5) end
-- closures
local function counter() local c = 0; return function() c = c + 1; return c end end
local c1, c2 = counter(), counter()
eq(c1(), 1); eq(c1(), 2); eq(c2(), 1)
local fns = {}
for i = 1, 3 do fns[i] = function() return i end end
eq(fns[1](), 1); eq(fns[3](), 3)
fns = {}
local j = 0
while j < 3 do j = j + 1; local k = j; fns[j] = function() k = k + 10; return k end end
eq(fns[1](), 11); eq(fns[1](), 21); eq(fns[2](), 12)
local function shared() local v = 0; return function() v = v + 1 return v end, function() return v end end
local inc, get = shared(); inc(); inc(); eq(get(), 2)
-- recursion / tail calls
local function fact(n) if n <= 1 then return 1 end return n * fact(n - 1) end
eq(fact(10), 3628800); eq(fact(20), 2432902008176640000)
local function loop(n, acc) if n == 0 then return acc end return loop(n - 1, acc + 1) end
eq(loop(1000000, 0), 1000000)
local function deep(n) if n == 0 then return 0 end return 1 + deep(n - 1) end
eq(deep(10000), 10000)
local ok, e = pcall(function() local function f() return 1 + f() end return f() end)
eq(ok, false); eq(type(e), "string")
local obj = {n = 0}
function obj:inc(k) self.n = self.n + (k or 1); return self end
obj:inc():inc(5); eq(obj.n, 6)
function obj.static(v) return v * 2 end
eq(obj.static(4), 8)
local ns = {a = {b = {}}}
function ns.a.b.f() return "deep" end
function ns.a.b:g() return self == ns.a.b end
eq(ns.a.b.f(), "deep"); eq(ns.a.b:g(), true)
-- tail call in method / varargs
local function tailv(...) return select('#', ...) end
local function tailc(...) return tailv(...) end
eq(tailc(1, 2, 3), 3)
-- string call syntax
local function id(x) return x end
eq(id"str", "str"); eq(id[[long]], "long"); eq(#id{1, 2}, 2)
-- <const> and <close>
local K <const> = 5; eq(K, 5)
eq(cerr("local x <const> = 1; x = 2"), "c:1: attempt to assign to const variable 'x'")
eq(cerr("local x <foo> = 1"), "c:1: unknown attribute 'foo'")
local log = {}
local function closer(name) return setmetatable({}, {__close = function(_, e) log[#log + 1] = name .. (e and ":err" or "") end}) end
do
  local a <close> = closer("a")
  local b <close> = closer("b")
  log[#log + 1] = "body"
end
eq(log[1], "body"); eq(log[2], "b"); eq(log[3], "a")
log = {}
local function f() local x <close> = closer("x"); return "ret" end
eq(f(), "ret"); eq(log[1], "x")
log = {}
for i = 1, 2 do local y <close> = closer("y" .. i); if i == 1 then goto cont end; log[#log + 1] = "i2" ::cont:: end
eq(table and 0 or 0, 0)
eq(log[1], "y1"); eq(log[2], "i2"); eq(log[3], "y2")
log = {}
local ok2, e2 = pcall(function() local z <close> = closer("z"); error("boom", 0) end)
eq(ok2, false); eq(e2, "boom"); eq(log[1], "z:err")
eq(err("local x <close> = 42"), "c:1: variable 'x' got a non-closable value")
local nilclose <close> = nil
local falseclose <close> = false
-- generic for with closing value
log = {}
local function iter() return function(_, i) i = i + 1; if i <= 2 then return i end end, nil, 0, closer("forclose") end
for i in iter() do log[#log + 1] = i end
eq(log[1], 1); eq(log[2], 2); eq(log[3], "forclose")
-- integer keys normalization
t = {}; t[1.0] = "a"; t[2^53] = "b"; eq(t[1], "a"); eq(t[2^53 | 0], "b")
t = {}; t[3] = 1; t[2] = 1; t[1] = 1; eq(#t, 3)
t = {10, 20, 30}; t[#t] = nil; eq(#t, 2); t[#t + 1] = 99; eq(t[3], 99)
-- next / pairs
t = {10, 20, 30, a = 1, b = 2}
local cnt = 0; for k, v in pairs(t) do cnt = cnt + 1 end; eq(cnt, 5)
for k in pairs(t) do t[k] = nil end; eq(next(t), nil)
local order = {}
for k, v in ipairs({1, 2, nil, 4}) do order[#order + 1] = v end; eq(#order, 2)
eq(next({}), nil); eq(next({5}), 1)
eq(err("return next({}, 'nokey')"), "c:1: invalid key to 'next'")
eq(err("local t = {} t[nil] = 1"), "c:1: index is nil")
eq(err("local t = {} t[0/0] = 1"), "c:1: index is NaN")
eq(({})[nil], nil)
-- multiple assignment order, nested tables
local m = {{1, 2}, {3, 4}}; eq(m[2][1], 3)
local big = {}; for i = 1, 1000 do big[i] = i * 2 end; eq(#big, 1000); eq(big[500], 1000)
for i = 1000, 1, -1 do big[i] = nil end; eq(#big, 0); eq(next(big), nil)
-- long strings & escapes
eq([[
x]], "x"); eq([==[a]]b]==], "a]]b"); eq("\65\066\x41\u{48}\u{20AC}", "ABAH\xE2\x82\xAC")
eq("a\z
    b", "ab"); eq("\\n", "\\" .. "n"); eq('\'', "'"); eq(#"\0ab", 3); eq("a\
b", "a\nb")
--[[ block
comment ]] eq(1, 1)
--[==[ another
]==] eq(2, 2)
print("ok")
