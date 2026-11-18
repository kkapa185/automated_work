local s = 0
for i = 1, 1000000 do s = s + i % 7 end
assert(s == 2999998)
local n, k = 0, 0
while k < 1000000 do k = k + 1; if k % 2 == 0 then n = n + 1 end end
assert(n == 500000)
