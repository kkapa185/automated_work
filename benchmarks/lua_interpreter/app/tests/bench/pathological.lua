-- limit: 10
-- worst-case shapes without needing the string library: deep call stacks, long operator chains, many closures
local function depth(n) if n == 0 then return 0 end return 1 + depth(n - 1) end
assert(depth(190000) == 190000)
local t = {}
local cur = t
for i = 1, 1000000 do cur.next = {}; cur = cur.next end
collectgarbage()
local fs = {}
for i = 1, 300000 do local v = i; fs[i] = function() v = v + 1; return v end end
assert(fs[300000]() == 300001)
local code = "return 0"
for i = 1, 5000 do code = code .. " + 1" end
assert(load(code)() == 5000)
local c = "return 'a'"
for i = 1, 2000 do c = c .. " .. 'b'" end
assert(#load(c)() == 2001)
