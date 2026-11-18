dofile("tests/cases/prelude.lua")
-- hardening / edge cases across features
-- many values
local big = {}; for i = 1, 5000 do big[i] = i end
eq(select('#', table.unpack(big)), 5000); eq(select(5000, table.unpack(big)), 5000)
local function count(...) return select('#', ...) end
eq(count(table.unpack(big)), 5000); eq(#{table.unpack(big)}, 5000)
-- deeply nested expressions / long chains
local src = "return " .. string.rep("(", 200) .. "1" .. string.rep(")", 200); eq(load(src)(), 1)
src = "return 1" .. string.rep(" + 1", 5000); eq(load(src)(), 5001)
src = "return '' " .. string.rep(".. 'x'", 2000); eq(#load(src)(), 2000)
src = "local t = {}" .. string.rep(" t[#t+1] = 1", 3000) .. " return #t"; eq(load(src)(), 3000)
-- many locals and upvalues
local parts = {}
for i = 1, 150 do parts[#parts + 1] = "local v" .. i .. " = " .. i end
parts[#parts + 1] = "return function() return v1 + v75 + v150 end"
eq(load(table.concat(parts, "\n"))()(), 226)
-- big strings
local s = string.rep("ab", 500000); eq(#s, 1000000); eq(s:sub(-2), "ab"); eq(select(2, s:gsub("a", "")), 500000)
eq(#table.concat({s, s}), 2000000); eq(s:find("ba", 1, true), 2); eq(#s:upper(), 1000000)
-- string keys, integer/float key identity, negative zero
local t = {}; t[0] = "zero"; t[-0.0] = "negzero"; eq(t[0], "negzero")
t = {}; t[1] = 1; t[1.5] = 2; t["1"] = 3; eq(t[1], 1); eq(t[1.5], 2); eq(t["1"], 3)
t = {[1] = "a", [2] = "b", [4] = "d"}; eq(t[4], "d"); t[3] = "c"; eq(#t, 4)
-- reverse fill and holes
t = {}; for i = 100, 1, -1 do t[i] = i end; eq(#t, 100)
t = {}; for i = 1, 100 do t[i] = i end; for i = 1, 100 do t[i] = nil end; eq(#t, 0); eq(next(t), nil)
-- table with float keys and removal during traversal
t = {}; for i = 1, 50 do t["k" .. i] = i end
local removed = 0; for k, v in pairs(t) do t[k] = nil; removed = removed + 1 end; eq(removed, 50); eq(next(t), nil)
-- reuse after clearing and growth
for round = 1, 3 do for i = 1, 100 do t["x" .. i] = i end; for k in pairs(t) do t[k] = nil end end; eq(next(t), nil)
-- integer overflow in loops and parsing
eq(math.maxinteger + 1 == math.mininteger, true); eq(-math.mininteger == math.mininteger, true)
eq(math.abs(math.mininteger), math.mininteger); eq(tostring(math.mininteger), "-9223372036854775808")
eq(tostring(-9223372036854775807 - 1), "-9223372036854775808"); eq(9007199254740993, 9007199254740993)
eq(string.format("%d", math.mininteger), "-9223372036854775808")
-- comparisons of mixed huge values
eq(math.maxinteger < 2^63, true); eq(math.mininteger <= -2^63, true); eq(math.maxinteger + 0.0 == 2^63, true)
eq(1 < 1.0000000000000002, true); eq(2^53 + 1 > 2^53, false)
-- tostring / tonumber round trips
for _, v in ipairs({0.1, 1/3, 123456.789, 1e-7, 2^40, -2.5e20}) do eq(tonumber(tostring(v)) ~= nil, true) end
eq(tonumber(string.format("%.17g", 0.1)), 0.1); eq(tonumber("0x7fffffffffffffff"), math.maxinteger)
-- string <-> number edge cases
eq("0x10" + 0, 16); eq("1e1" + 0, 10.0); eq(" 0x1p4 " + 0, 16.0); eq(pcall(function() return "1 2" + 0 end), false)
eq(#tostring(12345.678), 9); eq(2^63 // 1, 2^63); eq(7 // 2.0, 3.0); eq(-7 // 2.0, -4.0); eq(7.5 // 2, 3.0)
-- pcall/error interplay
eq(select(2, pcall(error, setmetatable({}, {__tostring = function() return "E" end}))) ~= nil, true)
local ok, e = pcall(function() local a <close> = setmetatable({}, {__close = function() error("in close", 0) end}); return 1 end)
eq(ok, false); eq(e, "in close")
ok, e = pcall(function() local a <close> = setmetatable({}, {__close = function() error("second", 0) end}); error("first", 0) end)
eq(e, "second")
-- error with levels through nested functions
local function l1() error("L", 3) end
local function l2() l1() end
local function l3() l2() end   -- level 3 points at the call l2() on this line (56)
ok, e = pcall(l3); eq(e, "tests/cases/edge.lua:56: L")
-- stack overflow is catchable and the interpreter keeps working
local function rec() return 1 + rec() end
ok, e = pcall(rec); eq(ok, false); eq(e:find("stack overflow", 1, true) ~= nil, true)
local depth = 0; local function d() depth = depth + 1; d() end; pcall(d); eq(depth > 1000, true)
ok = pcall(string.rep, "x", 100); eq(ok, true)
-- infinite recursion through metamethods does not crash
local loop = setmetatable({}, {}); getmetatable(loop).__index = loop
ok, e = pcall(function() return loop.x end); eq(ok, false)
local mm = setmetatable({}, {__add = function(a, b) return a + b end}); ok = pcall(function() return mm + 1 end); eq(ok, false)
-- goto semantic edge cases
do
  local i = 1
  ::top::
  if i <= 3 then i = i + 1; goto top end
  eq(i, 4)
end
for i = 1, 3 do
  local j = 0
  while true do j = j + 1; if j > 2 then goto out end end
  ::out::
end
-- closures in loops with goto continue capture fresh variables
local fs = {}
for i = 1, 3 do local x = i * 2; fs[#fs + 1] = function() return x end; if i == 2 then goto cont end; ::cont:: end
eq(fs[1](), 2); eq(fs[2](), 4); eq(fs[3](), 6)
-- varargs edge cases
local function v(...) local a, b, c = ...; return c, b, a end
eq(select('#', v()), 3); eq((v(1, 2, 3)), 3)
local function pass(...) return ... end
eq(select('#', pass(nil, nil, nil)), 3); eq(select('#', pass()), 0)
eq(select('#', (pass(1, 2))), 1)
-- method call on number literal & string literal
eq(("%d"):format(5), "5"); eq(#("abc"), 3)
-- integer division & modulo by negative numbers (floor semantics)
for _, c in ipairs({{7, 3}, {-7, 3}, {7, -3}, {-7, -3}}) do
  local a, b = c[1], c[2]
  eq(a // b * b + a % b, a)
  eq((a + 0.0) // b * b + (a + 0.0) % b, a + 0.0)
end
-- load with env and upvalues
local env = setmetatable({}, {__index = _G})
load("newglobal = 5", "c", "t", env)(); eq(env.newglobal, 5); eq(newglobal, nil)
-- _ENV manipulation
do local _ENV = setmetatable({}, {__index = _G}); zzz = 1; eq(zzz, 1); eq(_G.zzz, nil) end
-- os / io robustness
eq(io.write() == io.stdout, true)
eq(#os.date() > 0, true)
print("ok")
