-- R16: table library
local function err(f, ...) local ok, e = pcall(f, ...); assert(not ok); return e end
local t = {}
table.insert(t, "a"); table.insert(t, "c"); table.insert(t, 2, "b"); table.insert(t, 1, "z")
assert(table.concat(t, ",") == "z,a,b,c" and #t == 4)
table.insert(t, #t + 1, "end"); assert(t[5] == "end")
assert(err(table.insert, t, 0, "x") == "bad argument #2 to 'insert' (position out of bounds)")
assert(err(table.insert, t, 7, "x") == "bad argument #2 to 'insert' (position out of bounds)")
assert(err(table.insert, t) == "wrong number of arguments to 'insert'")
assert(err(table.insert, t, 1, 2, 3) == "wrong number of arguments to 'insert'")
assert(err(table.insert, 1, 2) == "bad argument #1 to 'insert' (table expected, got number)")
-- remove
local r = {1, 2, 3, 4}
assert(table.remove(r) == 4 and #r == 3 and table.remove(r, 1) == 1 and r[1] == 2 and #r == 2)
assert(table.remove(r, 2) == 3 and #r == 1 and table.remove(r, 1) == 2 and #r == 0)
assert(table.remove({}) == nil and table.remove({}, 0) == nil and select('#', table.remove({})) == 1)
local r2 = {1, 2, 3}; assert(table.remove(r2, 4) == nil and #r2 == 3)
assert(err(table.remove, {1, 2, 3}, 5) == "bad argument #2 to 'remove' (position out of bounds)")
assert(err(table.remove, {1, 2, 3}, -1) == "bad argument #2 to 'remove' (position out of bounds)")
-- concat
assert(table.concat({}) == "" and table.concat({1, 2, 3}) == "123" and table.concat({1, 2, 3}, ", ") == "1, 2, 3")
assert(table.concat({"a", "b", "c"}, "-", 2) == "b-c" and table.concat({"a", "b", "c"}, "-", 2, 3) == "b-c" and table.concat({"a", "b"}, "-", 3) == "")
assert(table.concat({1.5, 2, "x"}, " ") == "1.5 2 x")
assert(err(table.concat, {1, {}, 3}) == "invalid value (at index 2) in table for 'concat'")
assert(err(table.concat, {1, 2}, ",", 1, 3) == "invalid value (at index 3) in table for 'concat'")
-- unpack / pack
local a, b, c = table.unpack({1, 2, 3}); assert(a == 1 and b == 2 and c == 3)
assert(select('#', table.unpack({}, 1, 3)) == 3 and select('#', table.unpack({1, 2, 3}, 2)) == 2 and table.unpack({1, 2, 3}, 2, 3) == 2)
assert(select('#', table.unpack({}, 5, 4)) == 0 and select('#', table.unpack({n = 3}, 1, 0)) == 0)
assert(err(table.unpack, {}, 1, 1e8) == "too many results to unpack")
local p = table.pack(1, nil, 3, nil); assert(p.n == 4 and p[1] == 1 and p[2] == nil and p[3] == 3)
assert(table.pack().n == 0 and select('#', table.unpack(table.pack(nil, nil), 1, 2)) == 2)
local big = {}; for i = 1, 5000 do big[i] = i end
assert(select('#', table.unpack(big)) == 5000 and (select(5000, table.unpack(big))) == 5000)
-- move
local m = table.move({1, 2, 3}, 1, 3, 2); assert(m[1] == 1 and m[2] == 1 and m[3] == 2 and m[4] == 3)
m = table.move({1, 2, 3}, 2, 3, 1); assert(m[1] == 2 and m[2] == 3 and m[3] == 3)
local dst = table.move({1, 2, 3}, 1, 3, 1, {}); assert(#dst == 3 and dst[3] == 3)
assert(table.move({1, 2, 3}, 1, 0, 5)[5] == nil and #table.move({}, 1, 0, 1, {9}) == 1)
assert(err(table.move, {}, 0, math.maxinteger, 2) == "bad argument #3 to 'move' (too many elements to move)")
assert(err(table.move, {}, 1, 2, math.maxinteger) == "bad argument #4 to 'move' (destination wrap around)")
-- sort
local s = {5, 2, 8, 1, 9, 3, 7, 4, 6, 0}
table.sort(s); for i = 1, 10 do assert(s[i] == i - 1) end
table.sort(s, function(x, y) return x > y end); for i = 1, 10 do assert(s[i] == 10 - i) end
local words = {"banana", "apple", "Cherry", "date"}; table.sort(words); assert(table.concat(words, " ") == "Cherry apple banana date")
table.sort(words, function(x, y) return x:lower() < y:lower() end); assert(table.concat(words, " ") == "apple banana Cherry date")
local recs = {{n = "b", v = 2}, {n = "a", v = 2}, {n = "c", v = 1}}
table.sort(recs, function(x, y) if x.v ~= y.v then return x.v < y.v end return x.n < y.n end)
assert(recs[1].n == "c" and recs[2].n == "a" and recs[3].n == "b")
table.sort({}); table.sort({1}); local one = {2, 1}; table.sort(one); assert(one[1] == 1)
local mixed = {3, 1.5, 2, 0.5}; table.sort(mixed); assert(mixed[1] == 0.5 and mixed[4] == 3)
assert(err(table.sort, {1, "x", 2}) == "attempt to compare string with number" or err(table.sort, {1, "x", 2}) == "attempt to compare number with string")
local inv = {}; for i = 1, 100 do inv[i] = i end
assert(err(table.sort, inv, function(a, b) return true end) == "invalid order function for sorting")
assert(err(table.sort, {1, 2}, 5) == "bad argument #2 to 'sort' (function expected, got number)")
-- sort scale and worst-case shapes
local N = 100000
local big2 = {}; local seed = 12345
for i = 1, N do seed = (seed * 1103515245 + 12345) % 2147483648; big2[i] = seed end
table.sort(big2); for i = 2, N do assert(big2[i - 1] <= big2[i]) end
local asc = {}; for i = 1, N do asc[i] = i end; table.sort(asc); assert(asc[1] == 1 and asc[N] == N)
local desc = {}; for i = 1, N do desc[i] = N - i end; table.sort(desc); assert(desc[1] == 0 and desc[N] == N - 1)
local same = {}; for i = 1, N do same[i] = 7 end; table.sort(same); assert(same[N] == 7)
local organ = {}; for i = 1, N do organ[i] = i <= N / 2 and i or N - i end; table.sort(organ); for i = 2, N do assert(organ[i - 1] <= organ[i]) end
table.sort(big2, function(x, y) return x > y end); assert(big2[1] >= big2[N])
-- metamethod-aware access
local log = {}
local proxy = setmetatable({}, {__index = function(_, k) return k <= 3 and k * 10 or nil end, __len = function() return 3 end,
  __newindex = function(_, k, v) log[#log + 1] = k .. "=" .. tostring(v) end})
assert(table.concat(proxy, ",") == "10,20,30" and select('#', table.unpack(proxy)) == 3)
table.insert(proxy, 99); assert(log[1] == "4=99")
-- next/pairs order for arrays then hash; next errors
assert(err(next, {}, "nokey") == "invalid key to 'next'")
assert(select('#', next({})) == 1)
print("tables ok")
