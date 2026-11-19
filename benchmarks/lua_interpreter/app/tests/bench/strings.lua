-- limit: 10
-- R15/R23: string workloads at scale, including worst-case shapes (long runs of one token, many matches)
local big = ("a"):rep(1000000)
assert(big:match("^.-$") == big and #big:match(".*") == 1000000 and big:find("a$") == 1000000)
assert(select(2, big:gsub("a", "b")) == 1000000)
assert(select(2, big:gsub("", "-")) == 1000001)
local cnt = 0; for w in big:gmatch("a") do cnt = cnt + 1 end; assert(cnt == 1000000)
-- many words
local words = {}
for i = 1, 100000 do words[i] = "word" .. i end
local parts = {}
for i = 1, 100000 do parts[#parts + 1] = words[i] .. " " end
local joined = ""
for i = 1, 100000, 1000 do joined = joined .. words[i] end
local sp = ("x y "):rep(250000)
local n = 0; for w in sp:gmatch("%S+") do n = n + 1 end; assert(n == 500000)
assert(#sp:gsub("%s+", "") == 500000)
-- format / rep / byte / char / sub in loops
local acc = 0
for i = 1, 200000 do acc = acc + #string.format("%d:%s:%5.2f", i, "x", i / 3) end
assert(acc > 0)
local s = ("0123456789"):rep(100000)
local sum = 0
for i = 1, #s, 7 do sum = sum + s:byte(i) + #s:sub(i, i + 2) end
assert(sum > 0)
assert(#string.rep("abc", 10000000) == 30000000)
-- reverse / upper / lower on 1e7 bytes
local huge = ("ab"):rep(5000000)
assert(#huge:upper() == 10000000 and huge:reverse():sub(1, 2) == "ba")
-- pack/unpack in bulk
local packed = {}
for i = 1, 100000 do packed[#packed + 1] = string.pack("<i4d", i, i / 2) end
for i = 1, 100000, 997 do local a, b = string.unpack("<i4d", packed[i]); assert(a == i and b == i / 2) end
-- pathological backtracking is bounded by the pattern-depth limit rather than blowing the C stack
local ok, e = pcall(string.find, big, ("a?"):rep(250) .. "b")
assert(ok == false and e == "pattern too complex", e)
