local t = {}
for i = 1, 1000000 do t[#t + 1] = i end
assert(#t == 1000000)
local s = {}
for i = 1, 100000 do s[i] = (i * 7919) % 100003 end
table.sort(s)
for i = 2, #s do assert(s[i - 1] <= s[i]) end
local parts = {}
for i = 1, 100000 do parts[i] = tostring(i) end
local str = table.concat(parts, ",")
local c = 0
for _ in str:gmatch("%d+") do c = c + 1 end
assert(c == 100000)
local h = {}
for i = 1, 200000 do h["k" .. i] = i end
local sum = 0
for k, v in pairs(h) do sum = sum + v end
assert(sum == 200000 * 200001 // 2)
