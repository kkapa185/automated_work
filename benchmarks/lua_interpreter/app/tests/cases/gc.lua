-- R13: automatic garbage collection keeps memory bounded
local function kb() return collectgarbage("count") end
collectgarbage(); local base = kb()
-- 1e7 short-lived strings
local n = 0
for i = 1, 10000000 do local s = "k" .. i; n = n + #s end
assert(n > 0 and kb() < base + 60000, kb())
-- 2e6 tables incl. cycles and closures
for i = 1, 2000000 do local t = {i, {i}}; t.self = t; t.f = function() return t end end
assert(kb() < base + 60000, kb())
-- quadratic string building does not leak
local s = ""
for i = 1, 100000 do s = s .. "x" end
assert(#s == 100000)
s = nil
collectgarbage(); assert(kb() < base + 30000, kb())
-- live data survives collection (long linked list: iterative marking, no recursion)
local head = nil
for i = 1, 1000000 do head = {next = head, v = i} end
collectgarbage()
local c, p = 0, head
while p do c = c + 1; p = p.next end
assert(c == 1000000)
head = nil; collectgarbage()
assert(kb() < base + 30000, kb())
-- data referenced only from upvalues / varargs / coroutine-free frames survives GC during calls
local function mk() local data = {}; for i = 1, 1000 do data[i] = tostring(i) .. "x" end return function() return data end end
local keep = mk()
for i = 1, 20000 do local x = {i}; local y = "s" .. i end
collectgarbage()
local d = keep(); assert(#d == 1000 and d[1000] == "1000x" and d[1] == "1x")
-- deep recursion holding values across allocation-heavy calls
local function rec(k, v) if k == 0 then collectgarbage(); return v end local t = {v}; return rec(k - 1, t) end
assert(rec(1000, 1)[1] ~= nil)
local function rec2(k) if k == 0 then collectgarbage(); return 0 end local t = {k}; local r = rec2(k - 1); return r + t[1] end
assert(rec2(5000) == 5000 * 5001 // 2)
-- collectgarbage options
assert(type(collectgarbage("count")) == "number" and collectgarbage("isrunning") == true)
assert(collectgarbage("step") ~= nil and collectgarbage("incremental") ~= nil and collectgarbage("generational") ~= nil)
collectgarbage("incremental")
collectgarbage("stop"); assert(collectgarbage("isrunning") == false); collectgarbage("restart"); assert(collectgarbage("isrunning") == true)
assert(select(2, pcall(collectgarbage, "bogus")) == "bad argument #1 to 'collectgarbage' (invalid option 'bogus')")
print("gc ok")
