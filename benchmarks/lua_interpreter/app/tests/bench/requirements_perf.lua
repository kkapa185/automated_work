-- limit: 30
-- R23: the stated performance requirements, each asserted with its own time limit (os.clock, CPU seconds)
local function timed(name, limit, f)
  local c = os.clock(); f(); local dt = os.clock() - c
  assert(dt <= limit, string.format("%s took %.2fs (limit %ss)", name, dt, limit))
end
timed("fib(25)", 1, function()
  local function fib(n) if n < 2 then return n end return fib(n - 1) + fib(n - 2) end
  assert(fib(25) == 75025)
end)
timed("1e6 loop", 1, function() local s = 0; for i = 1, 1000000 do s = s + i end; assert(s == 500000500000) end)
timed("1e6 table inserts/gets", 2, function()
  local t = {}; for i = 1, 1000000 do t[#t + 1] = i end
  local s = 0; for i = 1, #t do s = s + t[i] end
  assert(s == 500000500000)
  local h = {}; for i = 1, 1000000 do h[i * 3] = i end
  for i = 1, 1000000 do assert(h[i * 3] == i) end
end)
timed("string building + sort 1e5", 2, function()
  local parts = {}
  for i = 1, 100000 do parts[i] = tostring((i * 7919) % 100003) end
  table.sort(parts)
  local s = table.concat(parts, ",")
  assert(#s > 100000)
  local nums = {}; for i = 1, 100000 do nums[i] = (i * 7919) % 100003 end
  table.sort(nums); for i = 2, #nums do assert(nums[i - 1] <= nums[i]) end
end)
timed("concat loop 1e5", 2, function() local s = ""; for i = 1, 100000 do s = s .. "x" end; assert(#s == 100000) end)
timed("string.rep 1e7", 1, function() assert(#string.rep("abc", 10000000) == 30000000) end)
timed("sieve 5e6", 5, function()
  local n = 5000000; local p = {}
  for i = 2, n do p[i] = true end
  for i = 2, math.floor(math.sqrt(n)) do if p[i] then for j = i * i, n, i do p[j] = false end end end
  local c = 0; for i = 2, n do if p[i] then c = c + 1 end end
  assert(c == 348513)
end)
timed("method calls 2e6", 2, function()
  local C = {}; C.__index = C
  function C:inc() self.n = self.n + 1 end
  local o = setmetatable({n = 0}, C); for i = 1, 2000000 do o:inc() end; assert(o.n == 2000000)
end)
timed("closures + varargs 1e6", 2, function()
  local function mk() local c = 0; return function(...) c = c + select('#', ...); return c end end
  local f = mk(); for i = 1, 1000000 do f(i, i) end; assert(f() == 2000000)
end)
timed("pcall/error 2e5", 2, function() for i = 1, 200000 do local ok = pcall(error, "x"); assert(not ok) end end)
timed("coroutine switches 5e5", 2, function()
  local co = coroutine.wrap(function() for i = 1, 500000 do coroutine.yield(i) end end)
  for i = 1, 500000 do assert(co() == i) end
end)
timed("gsub/find/format 1e5", 2, function()
  local s = ("hello world "):rep(10)
  for i = 1, 100000 do s:find("wor", 1, true); s:gsub("o", "0"); string.format("%d:%s", i, "x") end
end)
