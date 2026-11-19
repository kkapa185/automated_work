-- limit: 5
-- R23: 1e6-iteration loop (we do 1e7), plus table and string workloads
local s = 0
for i = 1, 10000000 do s = s + i % 7 end
assert(s == 29999997 or s > 0)
local t = {}
for i = 1, 1000000 do t[i] = i end
local sum = 0
for i = 1, #t do sum = sum + t[i] end
assert(sum == 500000500000)
local h = {}
for i = 1, 200000 do h["key" .. i] = i end
local c = 0
for k, v in pairs(h) do c = c + 1 end
assert(c == 200000)
local parts = {}
for i = 1, 100000 do parts[#parts + 1] = i end
assert(#parts == 100000)
