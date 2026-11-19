-- limit: 10
-- R16/R20/R23: library throughput: sort, insert/remove, concat, unpack, file io, math
local N = 200000
local t = {}
local seed = 1
for i = 1, N do seed = (seed * 1103515245 + 12345) % 2147483648; t[i] = seed end
table.sort(t)
for i = 2, N do assert(t[i - 1] <= t[i]) end
table.sort(t, function(a, b) return a > b end)
local q = {}
for i = 1, 1000000 do table.insert(q, i) end
for i = 1, 1000000 do table.remove(q) end
assert(#q == 0)
local parts = {}
for i = 1, 1000000 do parts[i] = i end
assert(#table.concat(parts, ",") == 6888895)
local u = {table.unpack(parts, 1, 5000)}
assert(#u == 5000)
-- files: 500k lines
local name = os.tmpname()
local f = io.open(name, "w")
for i = 1, 500000 do f:write("line ", i, "\n") end
f:close()
local c = 0
for l in io.lines(name) do c = c + 1 end
assert(c == 500000)
f = io.open(name); local all = f:read("a"); f:close(); assert(#all > 3000000)
os.remove(name)
local s = 0
for i = 1, 2000000 do s = s + math.floor(i / 3) + math.max(i, 5) + math.abs(-i) end
assert(s > 0)
for i = 1, 200000 do local x = math.random(1, 100); assert(x >= 1 and x <= 100) end
