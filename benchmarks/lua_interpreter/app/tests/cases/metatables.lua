-- R10: metatables and metamethods
local mt = {}
mt.__add = function(a, b) return "add" end; mt.__sub = function() return "sub" end; mt.__mul = function() return "mul" end
mt.__div = function() return "div" end; mt.__mod = function() return "mod" end; mt.__pow = function() return "pow" end
mt.__idiv = function() return "idiv" end; mt.__band = function() return "band" end; mt.__bor = function() return "bor" end
mt.__bxor = function() return "bxor" end; mt.__shl = function() return "shl" end; mt.__shr = function() return "shr" end
mt.__unm = function() return "unm" end; mt.__bnot = function() return "bnot" end; mt.__concat = function() return "concat" end
mt.__len = function() return 42 end
local o = setmetatable({}, mt)
assert(o + 1 == "add" and 1 + o == "add" and o - 1 == "sub" and o * 1 == "mul" and o / 1 == "div" and o % 1 == "mod")
assert(o ^ 1 == "pow" and o // 1 == "idiv" and o & 1 == "band" and o | 1 == "bor" and o ~ 1 == "bxor")
assert(o << 1 == "shl" and o >> 1 == "shr" and -o == "unm" and ~o == "bnot" and o .. "x" == "concat" and "x" .. o == "concat")
assert(1 .. 2 .. o == "1concat" and #o == 42)
-- __index / __newindex
local base = {foo = "basefoo"}
local d = setmetatable({}, {__index = base}); assert(d.foo == "basefoo" and d.bar == nil and rawget(d, "foo") == nil)
local chain = setmetatable({}, {__index = setmetatable({}, {__index = base})}); assert(chain.foo == "basefoo")
local fi = setmetatable({}, {__index = function(t, k) return k .. "!" end}); assert(fi.abc == "abc!" and fi[1] == "1!")
local log = {}
local ni = setmetatable({}, {__newindex = function(t, k, v) rawset(t, k, v * 2) end}); ni.x = 5; assert(ni.x == 10); ni.x = 7; assert(ni.x == 7)
local store = {}; local proxy = setmetatable({}, {__newindex = store}); proxy.a = 1; assert(rawget(proxy, "a") == nil and store.a == 1)
-- __call
local callable = setmetatable({}, {__call = function(self, a, b) return a + b, self end})
local r1, r2 = callable(1, 2); assert(r1 == 3 and r2 == callable)
-- __eq, __lt, __le
local eqmt = {__eq = function(a, b) return a.v == b.v end, __lt = function(a, b) return a.v < b.v end, __le = function(a, b) return a.v <= b.v end}
local e1, e2, e3 = setmetatable({v = 1}, eqmt), setmetatable({v = 1}, eqmt), setmetatable({v = 2}, eqmt)
assert(e1 == e2 and e1 ~= e3 and e1 < e3 and e1 <= e2 and e3 > e1 and e3 >= e1 and not (e3 < e1))
assert(e1 ~= 1 and not rawequal(e1, e2) and rawequal(e1, e1))
-- __tostring, __name, __metatable, __pairs
assert(tostring(setmetatable({}, {__tostring = function() return "OBJ" end})) == "OBJ")
local named = setmetatable({}, {__name = "MyType"}); assert(tostring(named) ~= nil and tostring(named) ~= "table")
local prot = setmetatable({}, {__metatable = "locked"}); assert(getmetatable(prot) == "locked")
local ok, e = pcall(setmetatable, prot, {}); assert(not ok and e == "cannot change a protected metatable")
local pr = setmetatable({}, {__pairs = function(t) return function(_, k) if not k then return 1, "one" end end, t, nil end})
local cnt = 0; for k, v in pairs(pr) do cnt = cnt + 1; assert(k == 1 and v == "one") end; assert(cnt == 1)
-- __close, __gc/__mode accepted
setmetatable({}, {__gc = function() end, __mode = "k"})
-- rawlen/rawget/rawset
local rl = setmetatable({}, {__len = function() return 99 end}); assert(#rl == 99 and rawlen(rl) == 0 and rawlen("abc") == 3)
-- inheritance pattern
local Animal = {}; Animal.__index = Animal
function Animal.new(name) return setmetatable({name = name}, Animal) end
function Animal:speak() return self.name .. " makes a sound" end
local Dog = setmetatable({}, {__index = Animal}); Dog.__index = Dog
function Dog.new(name) local d = Animal.new(name); return setmetatable(d, Dog) end
function Dog:speak() return self.name .. " barks" end
assert(Animal.new("cat"):speak() == "cat makes a sound" and Dog.new("rex"):speak() == "rex barks")
-- __index on missing method error
local okc, ec = pcall(function() local x = setmetatable({}, {__index = {}}); x:nomethod() end)
assert(not okc and ec == "tests/cases/metatables.lua:50: attempt to call a nil value (method 'nomethod')", ec)
-- integer vs float __eq with tables is raw
assert(setmetatable({}, {__eq = function() return true end}) ~= 1)
-- __concat with numbers; __len returning non-integer
local cm = setmetatable({}, {__concat = function(a, b) return (type(a) == "table" and "T" or a) .. (type(b) == "table" and "T" or b) end})
assert(cm .. 1 == "T1" and 1 .. cm == "1T" and "a" .. "b" .. cm == "abT")
-- __unm/__bnot get operand twice; __lt for mixed
local um = setmetatable({}, {__unm = function(a, b) return rawequal(a, b) end}); assert(-um == true)
print("metatables ok")
