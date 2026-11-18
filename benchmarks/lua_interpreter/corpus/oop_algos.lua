local Stack = {} Stack.__index = Stack
function Stack.new() return setmetatable({items = {}, size = 0}, Stack) end
function Stack:push(v) self.size = self.size + 1 self.items[self.size] = v end
function Stack:pop() local v = self.items[self.size] self.items[self.size] = nil self.size = self.size - 1 return v end
local s = Stack.new() for i = 1, 5 do s:push(i * 10) end print(s:pop(), s:pop(), s.size)
local function qsort(t) if #t <= 1 then return t end local p, l, r = t[1], {}, {} for i = 2, #t do if t[i] < p then l[#l + 1] = t[i] else r[#r + 1] = t[i] end end
  local res = qsort(l) res[#res + 1] = p for _, v in ipairs(qsort(r)) do res[#res + 1] = v end return res end
print(table.concat(qsort({5, 3, 8, 1, 9, 2, 7}), " "))
local memo = {} local function f(n) if n <= 2 then return 1 end if memo[n] then return memo[n] end local v = f(n - 1) + f(n - 2) memo[n] = v return v end print(f(90))
local primes = {} for i = 2, 60 do local p = true for j = 2, math.floor(math.sqrt(i)) do if i % j == 0 then p = false break end end if p then primes[#primes + 1] = i end end print(table.concat(primes, ","))
local function words(str) local c = {} for word in str:gmatch("%a+") do local w = word:lower() c[w] = (c[w] or 0) + 1 end return c end
local wc = words("The cat and the hat and THE bat") local ks = {} for k in pairs(wc) do ks[#ks + 1] = k end table.sort(ks) for _, k in ipairs(ks) do io.write(k, "=", wc[k], " ") end print()
print(string.format("%.3f", math.pi), math.floor(-3.5), math.ceil(-3.5), math.abs(-4), math.max(3, 9, 2), math.min(3, 9, 2), math.fmod(7, 3), math.modf(3.7))
print(os.time({year = 2020, month = 1, day = 1, hour = 12}) ~= nil, type(os.clock()), os.date("!%Y-%m-%d", 0))
