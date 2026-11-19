-- R12: coroutines
local co = coroutine
-- value passing both ways (manual-style example)
local c1 = co.create(function(a, b)
  assert(a == 1 and b == 2)
  local c = co.yield(a + b)
  assert(c == "x")
  local d, e = co.yield(c, "y")
  assert(d == nil and e == nil)
  return "done", 1, 2
end)
local r = {co.resume(c1, 1, 2)}; assert(#r == 2 and r[1] == true and r[2] == 3)
r = {co.resume(c1, "x")}; assert(#r == 3 and r[2] == "x" and r[3] == "y")
r = {co.resume(c1)}; assert(#r == 4 and r[1] == true and r[2] == "done" and r[4] == 2)
-- status transitions
local outer, inner
outer = co.create(function()
  assert(co.status(outer) == "running")
  inner = co.create(function() assert(co.status(outer) == "normal"); co.yield() end)
  co.resume(inner)
  assert(co.status(inner) == "suspended")
  co.yield()
end)
assert(co.status(outer) == "suspended"); co.resume(outer); assert(co.status(outer) == "suspended")
co.resume(outer); assert(co.status(outer) == "dead")
-- resume dead / non-suspended
local ok, e = co.resume(outer); assert(ok == false and e == "cannot resume dead coroutine")
local self; self = co.create(function() return co.resume(self) end)
local a, b, c = co.resume(self); assert(a == true and b == false and c == "cannot resume non-suspended coroutine")
-- running / isyieldable
local main, ismain = co.running(); assert(type(main) == "thread" and ismain == true and co.isyieldable() == false)
co.wrap(function() local t, m = co.running(); assert(m == false and co.isyieldable() and co.status(t) == "running") end)()
-- yield outside coroutine
ok, e = pcall(co.yield, 1); assert(not ok and e == "attempt to yield from outside a coroutine")
-- errors: resume returns false,msg; positions; non-string error values
local ce = co.create(function() error("oops") end)
ok, e = co.resume(ce); assert(ok == false and e == "tests/cases/coroutines.lua:36: oops", e)
assert(co.status(ce) == "dead")
local tobj = {}
ok, e = co.resume(co.create(function() error(tobj) end)); assert(not ok and e == tobj)
ok, e = co.resume(co.create(function() local x; x.y = 1 end)); assert(not ok and e == "tests/cases/coroutines.lua:41: attempt to index a nil value (local 'x')", e)
-- wrap: generators, error propagation with position prepended
local function gen(n) return co.wrap(function() for i = 1, n do co.yield(i) end end) end
local s = 0; for v in gen(10) do s = s + v end; assert(s == 55)
local w = co.wrap(function() error("werr") end)
ok, e = pcall(function() w() end)      -- wrap prepends the caller position to string errors (line 46)
assert(not ok and e == "tests/cases/coroutines.lua:46: tests/cases/coroutines.lua:45: werr", e)
w = co.wrap(function() return 1 end); w()
ok, e = pcall(function() w() end)
assert(not ok and e == "tests/cases/coroutines.lua:49: cannot resume dead coroutine", e)
local we = co.wrap(function() error({code = 7}) end)
ok, e = pcall(we); assert(not ok and e.code == 7)
-- yield across pcall, metamethods, iterators, nested coroutines
local log = {}
local c2 = co.wrap(function()
  local ok, v = pcall(function() local x = co.yield("in pcall"); error("after " .. x, 0) end)
  log[#log + 1] = tostring(ok) .. ":" .. v
  local mt = setmetatable({}, {__index = function(t, k) return co.yield("idx " .. k) end,
                               __add = function(a, b) return co.yield("add") end,
                               __call = function(self, x) return co.yield("call " .. x) end})
  log[#log + 1] = mt.foo; log[#log + 1] = mt + 1; log[#log + 1] = mt(5)
  for k in (function() return co.yield("iter") end) do log[#log + 1] = k; break end
  return "fin"
end)
assert(c2() == "in pcall"); assert(c2("resume") == "idx foo"); assert(c2("A") == "add"); assert(c2("B") == "call 5")
assert(c2("C") == "iter"); assert(c2("K") == "fin")
assert(log[1] == "false:after resume" and log[2] == "A" and log[3] == "B" and log[4] == "C" and log[5] == "K")
local nest = co.wrap(function() local inner = co.wrap(function() co.yield(1); co.yield(2) end); co.yield(inner() + inner()) end)
assert(nest() == 3)
-- many coroutines are reclaimed by GC
local live = {}
for i = 1, 20000 do
  local c = co.wrap(function(x) local y = co.yield(x + 1); return y * 2 end)
  assert(c(i) == i + 1)
  if i % 1000 == 0 then live[#live + 1] = c end
end
collectgarbage()
for i, c in ipairs(live) do assert(c(i) == i * 2) end
-- suspended coroutines keep their locals alive across GC
local holders = {}
for i = 1, 200 do
  local c = co.create(function() local t = {i, tostring(i)}; co.yield(); collectgarbage(); return t[1], t[2] end)
  co.resume(c); holders[i] = c
end
collectgarbage()
for i = 1, 200 do local ok, a, b = co.resume(holders[i]); assert(ok and a == i and b == tostring(i)) end
-- recursion inside coroutines, overflow is an error not a crash
local rc = co.wrap(function() local function d(n) if n == 0 then return 0 end return 1 + d(n - 1) end return d(500) end)
assert(rc() == 500)
local so = co.create(function() local function inf(n) return 1 + inf(n) end return inf(1) end)
ok, e = co.resume(so); assert(ok == false and type(e) == "string")
-- close
local cl = co.create(function() local x <close> = setmetatable({}, {__close = function() log.closed = true end}); co.yield(1) end)
co.resume(cl); assert(co.close(cl) == true and log.closed == true and co.status(cl) == "dead")
assert(co.close(co.create(print)) == true)
local ce2 = co.create(function() local x <close> = setmetatable({}, {__close = function(_, err) log.cerr = err end}); error("E", 0) end)
co.resume(ce2); ok, e = co.close(ce2); assert(ok == false and e == "E" and log.cerr == "E")
ok, e = pcall(co.close, main); assert(not ok and e == "cannot close a running coroutine")
-- wrap closes on error: pending tbc run
local wlog = {}
local wc = co.wrap(function() local x <close> = setmetatable({}, {__close = function() wlog[1] = "closed" end}); error("fail", 0) end)
pcall(wc); assert(wlog[1] == "closed")
-- argument validation
ok, e = pcall(co.create, 1); assert(not ok and e == "bad argument #1 to 'create' (function expected, got number)", e)
ok, e = pcall(co.resume, 1); assert(not ok and e == "bad argument #1 to 'resume' (coroutine expected, got number)", e)
-- passing many values
local many = co.wrap(function(...) local t = {...}; co.yield(#t); return ... end)
assert(many(1, 2, 3) == 3)
local function pass(...) return select('#', ...), ... end
local echo = co.wrap(function(...) while true do co.yield(pass(...)) end end)
assert(echo(nil, nil, nil) == 3)
print("coroutines ok")
