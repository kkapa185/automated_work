-- R7/R9: statements, closures, varargs, goto, tail calls
-- multiple assignment: RHS evaluated before assignment
local a, b = 1, 2; a, b = b, a; assert(a == 2 and b == 1)
local i, t = 3, {}; i, t[i] = i + 1, 20; assert(i == 4 and t[3] == 20 and t[4] == nil)  -- manual example
local x, y, z = (function() return 1, 2, 3 end)(); assert(x == 1 and y == 2 and z == 3)
x, y, z = (function() return 1, 2, 3 end)(), 10; assert(x == 1 and y == 10 and z == nil)
x, y = ((function() return 1, 2 end)()); assert(x == 1 and y == nil)
local function mr() return 1, 2, 3 end
assert(select('#', mr()) == 3 and select('#', (mr())) == 1 and select('#', mr(), mr()) == 4)
local tt = {mr(), mr()}; assert(#tt == 4)
tt = {mr(), (mr())}; assert(#tt == 2)
tt = {[1] = "a", "b"}; assert(tt[1] == "b")
-- if / while / repeat
local r = {}
for n = 1, 5 do
  if n == 1 then r[#r + 1] = "one" elseif n == 2 then r[#r + 1] = "two" elseif n == 3 then r[#r + 1] = "three" else r[#r + 1] = "many" end
end
assert(#r == 5 and r[1] == "one" and r[3] == "three" and r[5] == "many")
local n = 0; while n < 10 do n = n + 1; if n == 5 then break end end; assert(n == 5)
n = 0; repeat local k = n; n = n + 1 until k >= 3; assert(n == 4)       -- until sees body locals
-- nested break / goto continue
local out = {}
for i = 1, 3 do for j = 1, 3 do if j == 2 then goto continue end; if i == 3 then break end; out[#out + 1] = i * 10 + j; ::continue:: end end
assert(#out == 4 and out[1] == 11 and out[2] == 13 and out[3] == 21 and out[4] == 23)
do local k = 0; ::top:: k = k + 1; if k < 5 then goto top end; assert(k == 5) end
do goto skip; local zz; ::skip:: end   -- label at end of block: allowed even with local between
assert(select(2, load("goto nope", "=c")) == "c:1: no visible label 'nope' for <goto> at line 1")
assert(select(2, load("do ::l:: end goto l", "=c")) == "c:1: no visible label 'l' for <goto> at line 1")
assert(select(2, load("::l:: ::l::", "=c")) == "c:1: label 'l' already defined on line 1")
assert(select(2, load("goto f; local a; ::f:: print(a)", "=c")) == "c:1: <goto f> at line 1 jumps into the scope of local 'a'")
assert(select(2, load("break", "=c")) == "c:1: break outside a loop at line 1")
-- closures: fresh upvalue per iteration, shared among closures
local fs = {}
for i = 1, 3 do local c = i; fs[i] = function() c = c + 1; return c end end
assert(fs[1]() == 2 and fs[1]() == 3 and fs[2]() == 3 and fs[3]() == 4)
local function counter() local c = 0; return function() c = c + 1; return c end, function() return c end end
local inc, get = counter(); inc(); inc(); assert(get() == 2)
local ws = {}
local j = 0
while j < 3 do j = j + 1; local v = j * 2; ws[j] = function() v = v + 1; return v end end
assert(ws[1]() == 3 and ws[1]() == 4 and ws[2]() == 5 and ws[3]() == 7)
local rec; rec = function(n) if n == 0 then return 0 end return n + rec(n - 1) end; assert(rec(10) == 55)
local function outer() local v = 1; local function mid() local function inner() v = v + 1; return v end; return inner end; return mid(), function() return v end end
local inn, gv = outer(); inn(); assert(gv() == 2)
-- scoping
local sx = 1; do local sx = sx + 1; assert(sx == 2) end; assert(sx == 1)
local function shadow(sx) return sx end; assert(shadow(5) == 5 and sx == 1)
local lf; local function lfun() return lf end; lf = 7; assert(lfun() == 7)
-- varargs
local function va(...) return select('#', ...), ... end
assert(va() == 0 and va(nil) == 1 and select('#', va(nil, nil)) == 3)
local function va2(...) local a, b = ...; return a, b, select('#', ...) end
local p, q, cnt = va2(1); assert(p == 1 and q == nil and cnt == 1)
local function va3(...) return {...}, select('#', ...) end
local vt, vn = va3(1, nil, 3); assert(vn == 3 and vt[1] == 1 and vt[3] == 3)
assert(select(-1, 1, 2, 3) == 3 and select(-2, 1, 2, 3) == 2 and select(2, 1, 2, 3) == 2 and select('#') == 0)
assert(select('#', select(4, 1, 2, 3)) == 0)
local function va4(a, ...) local t = {...}; return a, #t end; local fa, fb = va4(1, 2, 3); assert(fa == 1 and fb == 2)
assert((function(...) return ... end)(1, 2, 3) == 1)
-- method calls and function statements
local obj = {v = 10}
function obj:get(d) return self.v + (d or 0) end
function obj.static(a) return a end
assert(obj:get() == 10 and obj:get(5) == 15 and obj.get(obj, 1) == 11 and obj.static(3) == 3)
local nest = {a = {b = {}}}
function nest.a.b.f(x) return x * 2 end; function nest.a.b:m(x) return self == nest.a.b and x end
assert(nest.a.b.f(4) == 8 and nest.a.b:m(9) == 9)
-- string call forms
local function id(...) return ... end
assert(id"str" == "str" and id[[long]] == "long" and #id{1, 2, 3} == 3 and type(id{}) == "table")
-- tail calls: constant stack
local function loop(n, acc) if n == 0 then return acc end return loop(n - 1, acc + 1) end
assert(loop(1000000, 0) == 1000000)
local function ping(n) if n == 0 then return "done" end return (function(m) return ping(m) end)(n - 1) end
assert(ping(200000) == "done")
local tc = {}; function tc:go(n) if n == 0 then return "ok" end return self:go(n - 1) end; assert(tc:go(300000) == "ok")
-- deep (non-tail) recursion
local function depth(n) if n == 0 then return 0 end return 1 + depth(n - 1) end
assert(depth(100000) == 100000)
-- runaway recursion gives a catchable error
local function inf(n) return 1 + inf(n + 1) end
local ok2, e2 = pcall(inf, 1)
assert(not ok2 and type(e2) == "string")
assert(select(2, load("for i = 1, 3 do i = 5 end", "=c")) == "c:1: attempt to assign to const variable 'i'")
-- generic for with custom iterator + closing value ignored when nil
local function range(n) local i = 0; return function() i = i + 1; if i <= n then return i end end end
local sum = 0; for v in range(4) do sum = sum + v end; assert(sum == 10)
local function stateless(s, c) if c < s then return c + 1, c * 2 end end
sum = 0; for a, b in stateless, 3, 0 do sum = sum + a + b end; assert(sum == 1 + 0 + 2 + 2 + 3 + 4)
-- pairs / next / ipairs
local pt = {10, 20, 30, k = "v", [100] = "h"}
local cnt2, ks = 0, 0
for k, v in pairs(pt) do cnt2 = cnt2 + 1 end; assert(cnt2 == 5)
for k, v in ipairs({1, 2, nil, 4}) do ks = ks + 1 end; assert(ks == 2)
assert(next({}) == nil and next({5}) == 1 and select(2, next({5})) == 5 and type(next) == "function")
for k in pairs(pt) do pt[k] = nil end; assert(next(pt) == nil)   -- clearing during traversal is allowed
-- integer keys, holes and length
local h = {}; for i = 1, 100 do h[i] = i end; assert(#h == 100)
for i = 100, 51, -1 do h[i] = nil end; assert(#h == 50)
local rv = {}; for i = 10, 1, -1 do rv[i] = i end; assert(#rv == 10)
local sp = {}; sp[1000000] = 1; assert(#sp == 0 and sp[1000000] == 1)
assert(#{1, 2, 3, nil} == 3 and #{n = 1} == 0 and #{nil, nil, 3} == 3)
-- long concat chains and string identity
local parts = {}; for i = 1, 10 do parts[i] = i end
assert(1 .. 2 .. 3 .. 4 .. 5 .. 6 .. 7 .. 8 .. 9 .. 10 == "12345678910")
local s1 = "abc" .. "def"; assert(s1 == "abcdef" and #s1 == 6)
local k1, k2 = "key" .. 1, "key1"; local kt = {[k1] = "v"}; assert(kt[k2] == "v")
-- _ENV and globals
gx = 5; assert(_G.gx == 5 and _ENV == _G); _G.gy = 6; assert(gy == 6)
local function envf() local _ENV = {v = 3}; return v end; assert(envf() == 3)
do local _ENV = setmetatable({}, {__index = _G}); newglobal = 1; assert(_G.newglobal == nil) end
assert(load("return x", "=c", "t", {x = 42})() == 42)
-- integer/float keys, booleans as keys
local bk = {[true] = 1, [false] = 2}; assert(bk[true] == 1 and bk[false] == 2)
print("language ok")
