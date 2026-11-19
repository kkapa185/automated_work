-- R26: the interpreter reports errors instead of crashing on hostile or extreme input
local function try(f, ...) local ok, e = pcall(f, ...); return ok, e end
local function failsWith(pattern, f, ...) local ok, e = pcall(f, ...); return not ok and type(e) == "string" and e:find(pattern) ~= nil end
assert(failsWith("resulting string too large", string.rep, "x", 1e10))
assert(failsWith("resulting string too large", string.rep, "ab", 1e9, "cd"))
assert(failsWith("invalid conversion", string.format, "%99999d", 1))
assert(failsWith("invalid conversion", string.format, "%.100f", 1))
assert(#string.format("%99.99f", 1e308) > 100 and #string.format("%s", ("x"):rep(1e6)) == 1000000)
-- runaway metamethod recursion and chains
assert(failsWith("stack overflow", function() local t = setmetatable({}, {}); getmetatable(t).__tostring = function(s) return tostring(s) end; return tostring(t) end))
assert(failsWith("chain too long", function() local a = setmetatable({}, {}); getmetatable(a).__index = a; return a.x end))
assert(failsWith("chain too long", function() local a = setmetatable({}, {}); getmetatable(a).__newindex = a; a.x = 1 end))
assert(failsWith("stack overflow", function() local a = setmetatable({}, {}); getmetatable(a).__call = a; return a() end))
assert(failsWith("stack overflow", function() local mt = {}; mt.__eq = function(a, b) return a == b end; return setmetatable({}, mt) == setmetatable({}, mt) end))
assert(failsWith("stack overflow", function() local mt = {}; mt.__concat = function(a, b) return a .. b end; return setmetatable({}, mt) .. "x" end))
assert(failsWith("stack overflow", function() local function f(s) return (s:gsub(".", f)) end return f("abc") end))
-- errors thrown by callbacks propagate cleanly out of library functions
assert(failsWith("cmp", table.sort, {3, 2, 1, 5, 4, 7, 6, 9, 8, 10, 12, 11, 14}, function() error("cmp") end))
assert(failsWith("boom", string.gsub, "abc", ".", function() error("boom") end))
do local lf, le = load(function() error("boom") end); assert(lf == nil and le:find("boom")) end
-- binary chunks and garbage source are rejected
assert(load("\27Lua\0\0") == nil and load("\0\0\0") == nil and load("\255\254") == nil)
assert(load("x = 'unterminated") == nil and load("x = [[ never closed") == nil and load("--[[ never closed") == nil)
assert(load("return 0x") == nil and load("return 1e") == nil and load("return 1..2") == nil and load("return ...") ~= nil)
assert(load(("x = 1\n"):rep(100000)) ~= nil)
-- syntax nesting limits
local function nested(open, close, n) return load("return " .. open:rep(n) .. "1" .. close:rep(n)) end
assert(nested("(", ")", 100) ~= nil)
local f, e = nested("(", ")", 300); assert(f == nil and e:find("too many syntax levels"))
f, e = nested("{", "}", 300); assert(f == nil and e:find("too many syntax levels"))
f, e = load(("do "):rep(300) .. ("end "):rep(300)); assert(f == nil and e:find("too many syntax levels"))
f, e = load(("function f() "):rep(300) .. ("end "):rep(300)); assert(f == nil and e:find("too many syntax levels"))
f, e = load("return " .. ("- "):rep(300) .. "1"); assert(f == nil and e:find("too many syntax levels"))
f, e = load("return " .. ("not "):rep(300) .. "1"); assert(f == nil and e:find("too many syntax levels"))
assert(load("return " .. ("a."):rep(10000) .. "a") ~= nil)                                   -- long suffix chains are iterative
assert(load("return f" .. ("()"):rep(10000)) ~= nil)
-- huge but legal programs
local big = {"local t = {"}; for i = 1, 200000 do big[#big + 1] = i .. "," end; big[#big + 1] = "} return #t"
assert(load(table.concat(big))() == 200000)
local chain = {"local x = 5 if x == 0 then "}; for i = 1, 20000 do chain[#chain + 1] = "elseif x == " .. i .. " then " end; chain[#chain + 1] = "end return x"
assert(load(table.concat(chain))() == 5)
local cat = {"return 'a'"}; for i = 1, 200000 do cat[#cat + 1] = " .. 'b'" end
assert(#load(table.concat(cat))() == 200001)
local add = {"return 0"}; for i = 1, 20000 do add[#add + 1] = " + 1" end
assert(load(table.concat(add))() == 20000)
-- the same inside a coroutine (small C stack)
assert(coroutine.wrap(function() return #load(table.concat(cat))() end)() == 200001)
assert(coroutine.wrap(function() return load(table.concat(add))() end)() == 20000)
-- huge argument / result lists are an error rather than a stack smash
local t3 = {}; for i = 1, 3000000 do t3[i] = i end
assert(select('#', table.unpack(t3)) == 3000000)
assert(failsWith("too many results to unpack", function() return coroutine.wrap(function() return select('#', table.unpack(t3)) end)() end))
assert(failsWith("stack overflow", function() return coroutine.wrap(function() return load("return select('#', " .. ("1,"):rep(1000000) .. "1)")() end)() end))
assert(select('#', string.byte(("x"):rep(100000), 1, -1)) == 100000)
assert(failsWith("string slice too long", string.byte, ("x"):rep(2000000), 1, -1))
-- deep recursion everywhere is bounded
local function rec(n) return 1 + rec(n + 1) end
assert(failsWith("stack overflow", rec, 1))
assert(failsWith("stack overflow", function() return coroutine.wrap(function() return rec(1) end)() end))
assert(failsWith("stack overflow", function() local function f(n) local ok, e = pcall(f, n + 1); if not ok then error(e, 0) end return 1 end; return f(1) end))
local depth = 0
local function rec2() depth = depth + 1; return rec2() + 1 end
assert(failsWith("stack overflow", rec2) and depth > 10000)
-- coroutines nested very deeply
local function nest(n) if n == 0 then return 0 end return coroutine.wrap(function() return nest(n - 1) + 1 end)() end
assert(nest(1000) == 1000)
-- numeric edge cases do not trap
assert(math.mininteger // -1 == math.mininteger and math.mininteger % -1 == 0 and math.abs(math.mininteger) == math.mininteger)
assert(tonumber("1" .. ("0"):rep(400)) == math.huge and tonumber("0x" .. ("f"):rep(100)) == -1)
assert(string.format("%d", math.mininteger) == "-9223372036854775808" and tostring(math.mininteger) == "-9223372036854775808")
assert(1e308 * 10 == math.huge and -1e308 * 10 == -math.huge and (0/0) ~= (0/0))
assert(failsWith("number has no integer representation", function() return 2^63 | 0 end))
assert(failsWith("'for' step is zero", function() for i = 1, 2, 0 do end end))
for i = math.maxinteger - 1, math.maxinteger do assert(i >= math.maxinteger - 1) end
for i = math.mininteger, math.mininteger + 2 do assert(i < 0) end
-- table edge cases
local sparse = {}; sparse[2^40] = 1; sparse[-1] = 2; sparse[0] = 3; sparse[1.5] = 4; assert(#sparse == 0 and sparse[2^40] == 1 and sparse[0] == 3)
local grow = {}; for i = 1, 1000 do grow[i] = i end; for i = 1, 1000 do grow[i] = nil end; assert(#grow == 0 and next(grow) == nil)
local rev = {}; for i = 1000, 1, -1 do rev[i] = i end; assert(#rev == 1000)
local mix = {}; for i = 1, 100 do mix[i] = i; mix["k" .. i] = i end; for i = 1, 100 do mix[i] = nil end; assert(#mix == 0)
local cnt = 0; for k in pairs(mix) do cnt = cnt + 1; mix[k] = nil end; assert(cnt == 100 and next(mix) == nil)
-- GC under pressure while holding many live objects across calls
local live = {}
for i = 1, 200000 do live[i] = {i, tostring(i)} end
for i = 1, 20 do local junk = {}; for j = 1, 50000 do junk[j] = {j} end end
for i = 1, 200000, 997 do assert(live[i][1] == i and live[i][2] == tostring(i)) end
print("robustness ok")
