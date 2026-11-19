-- table array/hash part invariants: border validity, traversal completeness, migration of integer keys into the array part
local seed = 7
local function rnd(n) seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n + 1 end
for round = 1, 200 do
  local t, ref, cnt = {}, {}, 0
  local range = ({10, 100, 1000})[round % 3 + 1]
  for step = 1, 3000 do
    local k = rnd(range)
    if rnd(4) == 1 then t[k] = nil; ref[#ref + 1] = nil; else t[k] = step end
    if step % 500 == 0 then
      -- check border validity and traversal completeness
      local n = #t
      assert(n == 0 or t[n] ~= nil, "border")
      assert(t[n + 1] == nil, "border+1")
      local seen = 0; for kk, vv in pairs(t) do assert(t[kk] == vv); seen = seen + 1 end
      local c = 0; for i = 1, range do if t[i] ~= nil then c = c + 1 end end
      assert(c == seen, "pairs count " .. c .. " vs " .. seen)
    end
  end
end
-- descending / offset fills
local d = {}; for i = 5000, 2, -1 do d[i] = i end; d[1] = 1; assert(#d == 5000)
local o = {}; for i = 2, 100000 do o[i] = i end; assert(o[2] == 2 and o[100000] == 100000 and o[1] == nil)
local c = 0; for k, v in pairs(o) do c = c + 1 end; assert(c == 99999)
o[1] = 1; assert(#o == 100000)
print("table_internals ok")
