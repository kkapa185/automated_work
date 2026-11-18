dofile("tests/cases/prelude.lua")
-- R17
local co = coroutine.create(function(a, b)
  local c = coroutine.yield(a + b)
  local d, e = coroutine.yield(c * 2)
  return d + e, "end"
end)
eq(coroutine.status(co), "suspended")
local ok, v = coroutine.resume(co, 1, 2); eq(ok, true); eq(v, 3)
ok, v = coroutine.resume(co, 10); eq(v, 20)
local ok3, r1, r2 = coroutine.resume(co, 5, 6); eq(ok3, true); eq(r1, 11); eq(r2, "end")
eq(coroutine.status(co), "dead")
local ok4, msg = coroutine.resume(co); eq(ok4, false); eq(msg, "cannot resume dead coroutine")
-- wrap as generator
local function range(n) return coroutine.wrap(function() for i = 1, n do coroutine.yield(i) end end) end
local sum = 0; for i in range(5) do sum = sum + i end; eq(sum, 15)
-- status from inside / normal
local outer, inner
outer = coroutine.create(function()
  inner = coroutine.create(function() eq(coroutine.status(outer), "normal"); eq(coroutine.status(inner), "running") end)
  coroutine.resume(inner)
  eq(coroutine.status(outer), "running")
end)
eq(select(1, coroutine.resume(outer)), true); eq(coroutine.status(inner), "dead")
-- running / isyieldable
local main, ismain = coroutine.running(); eq(ismain, true); eq(type(main), "thread"); eq(coroutine.isyieldable(), false)
coroutine.wrap(function() local c, m = coroutine.running(); eq(m, false); eq(coroutine.isyieldable(), true) end)()
eq(type(coroutine.create(print)), "thread"); eq(tostring(main):sub(1, 7), "thread:")
-- errors
eq(err("coroutine.yield(1)"), "c:1: attempt to yield from outside a coroutine")
co = coroutine.create(function() error("oops") end)
ok, msg = coroutine.resume(co)
eq(ok, false); eq(msg:find("oops", 1, true) ~= nil, true); eq(coroutine.status(co), "dead")
local tbl = {}
ok, msg = coroutine.resume(coroutine.create(function() error(tbl) end)); eq(msg, tbl)
ok, msg = coroutine.resume(coroutine.create(function() local x = nil; return x.y end)); eq(msg:find("attempt to index a nil value (local 'x')", 1, true) ~= nil, true)
eq(err("local f = coroutine.wrap(function() error('boom', 0) end) f()"), "c:1: boom")
eq(err("local f = coroutine.wrap(function() end) f() f()"), "c:1: cannot resume dead coroutine")
eq(select(2, pcall(coroutine.wrap(function() error("boom", 0) end))), "boom")
eq(select(2, pcall(coroutine.wrap(function() error({}, 0) end))) ~= nil, true)
eq(err("coroutine.resume(1)"), "c:1: bad argument #1 to 'resume' (coroutine expected, got number)")
eq(err("coroutine.create(1)"), "c:1: bad argument #1 to 'create' (function expected, got number)")
local self_co; self_co = coroutine.create(function() return coroutine.resume(self_co) end)
ok, msg, msg2 = coroutine.resume(self_co); eq(ok, true); eq(msg, false); eq(msg2, "cannot resume non-suspended coroutine")
-- yield across pcall, in nested calls and iterators
co = coroutine.wrap(function()
  local ok, e = pcall(function() coroutine.yield("in pcall"); error("after", 0) end)
  coroutine.yield(tostring(ok) .. ":" .. e)
  return "fin"
end)
eq(co(), "in pcall"); eq(co(), "false:after"); eq(co(), "fin")
local function deep(n) if n == 0 then coroutine.yield("bottom") else deep(n - 1) end return n end
co = coroutine.wrap(function() deep(50); return "done" end); eq(co(), "bottom"); eq(co(), "done")
-- varargs through yield/resume
co = coroutine.create(function(...) local a = {coroutine.yield(...)}; return #a end)
local _, a1, a2, a3 = coroutine.resume(co, 1, 2, 3); eq(a3, 3)
eq(select(2, coroutine.resume(co, "x", "y")), 2)
eq(select('#', coroutine.resume(coroutine.create(function() end))), 1)
-- coroutine.wrap inside coroutine.wrap (producer/filter/consumer)
local function producer() return coroutine.wrap(function() for i = 1, 4 do coroutine.yield(i) end end) end
local function filter(src) return coroutine.wrap(function() for v in src do if v % 2 == 0 then coroutine.yield(v * 10) end end end) end
local res = {}; for v in filter(producer()) do res[#res + 1] = v end; eq(table.concat(res, ","), "20,40")
-- close
co = coroutine.create(function() coroutine.yield() end)
coroutine.resume(co); eq(coroutine.close(co), true); eq(coroutine.status(co), "dead")
eq(coroutine.close(coroutine.create(print)), true)
local closed = {}
co = coroutine.create(function()
  local x <close> = setmetatable({}, {__close = function() closed[#closed + 1] = "x" end})
  coroutine.yield(1)
  closed[#closed + 1] = "not reached"
end)
coroutine.resume(co); eq(coroutine.close(co), true); eq(closed[1], "x"); eq(#closed, 1)
co = coroutine.create(function() error("E", 0) end); coroutine.resume(co)
local cok, cerr = coroutine.close(co); eq(cok, false); eq(cerr, "E")
co = coroutine.create(function()
  local x <close> = setmetatable({}, {__close = function() error("close err", 0) end})
  coroutine.yield()
end)
coroutine.resume(co); cok, cerr = coroutine.close(co); eq(cok, false); eq(cerr, "close err")
eq(err("local co co = coroutine.create(function() coroutine.close(co) end) local ok, e = coroutine.resume(co) error(e, 0)"), "c:1: cannot close a running coroutine")
-- many switches
local counter = 0
co = coroutine.wrap(function() while true do counter = counter + 1; coroutine.yield() end end)
for i = 1, 20000 do co() end; eq(counter, 20000)
-- many coroutines
local cos = {}
for i = 1, 500 do cos[i] = coroutine.create(function(x) local y = coroutine.yield(x * 2); return y + i end) end
local total = 0
for i = 1, 500 do local _, v = coroutine.resume(cos[i], i); total = total + v end
for i = 1, 500 do local _, v = coroutine.resume(cos[i], 1); total = total + v end
eq(total, 2 * 125250 + 500 + 125250)
print("ok")
