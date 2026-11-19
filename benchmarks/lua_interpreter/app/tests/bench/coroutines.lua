-- limit: 10
-- R12/R23: coroutine switching and creation throughput; deep recursion inside coroutines
local co = coroutine
local gen = co.wrap(function() for i = 1, 1000000 do co.yield(i) end return 0 end)
local sum = 0
for i = 1, 1000000 do sum = sum + gen() end
assert(sum == 500000500000)
for i = 1, 100000 do
  local c = co.create(function(a) local b = co.yield(a); return b end)
  co.resume(c, 1); co.resume(c, 2)
end
local function chain(n) if n == 0 then return 0 end return 1 + chain(n - 1) end
assert(co.wrap(function() return chain(1000) end)() == 1000)
-- 10000 simultaneously suspended coroutines
local cs = {}
for i = 1, 10000 do cs[i] = co.wrap(function() co.yield(i); return i * 2 end); cs[i]() end
for i = 1, 10000 do assert(cs[i]() == i * 2) end
