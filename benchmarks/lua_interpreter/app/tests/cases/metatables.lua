dofile("tests/cases/prelude.lua")
-- R10
local V = {}
V.__index = V
V.__add = function(a, b) return setmetatable({x = a.x + b.x}, V) end
V.__sub = function(a, b) return setmetatable({x = a.x - b.x}, V) end
V.__mul = function(a, b) if type(b) == "number" then return setmetatable({x = a.x * b}, V) else return setmetatable({x = a * b.x}, V) end end
V.__div = function(a, b) return "div" end
V.__mod = function(a, b) return "mod" end
V.__pow = function(a, b) return "pow" end
V.__idiv = function(a, b) return "idiv" end
V.__band = function(a, b) return "band" end
V.__bor = function(a, b) return "bor" end
V.__bxor = function(a, b) return "bxor" end
V.__shl = function(a, b) return "shl" end
V.__shr = function(a, b) return "shr" end
V.__unm = function(a) return setmetatable({x = -a.x}, V) end
V.__bnot = function(a) return "bnot" end
V.__len = function(a) return 42 end
V.__eq = function(a, b) return a.x == b.x end
V.__lt = function(a, b) return a.x < b.x end
V.__le = function(a, b) return a.x <= b.x end
V.__concat = function(a, b) return "cat" end
V.__call = function(self, a, b) return "called", a, b end
V.__tostring = function(a) return "V(" .. a.x .. ")" end
local function new(x) return setmetatable({x = x}, V) end
local a, b = new(1), new(2)
eq((a + b).x, 3); eq((b - a).x, 1); eq((a * 3).x, 3); eq((3 * b).x, 6)
eq(a / b, "div"); eq(a % b, "mod"); eq(a ^ b, "pow"); eq(a // b, "idiv")
eq(a & b, "band"); eq(a | 1, "bor"); eq(1 ~ a, "bxor"); eq(a << 1, "shl"); eq(a >> 1, "shr")
eq((-a).x, -1); eq(~a, "bnot"); eq(#a, 42); eq(a == new(1), true); eq(a ~= new(1), false); eq(a == b, false)
eq(a < b, true); eq(a <= b, true); eq(a > b, false); eq(a >= b, false)
eq(a .. "s", "cat"); eq("s" .. a, "cat"); eq(1 .. a, "cat")
local r1, r2, r3 = a(10, 20); eq(r1, "called"); eq(r2, 10); eq(r3, 20)
eq(tostring(a), "V(1)")
-- __index / __newindex
local base = {foo = "basefoo"}
local d = setmetatable({}, {__index = base})
eq(d.foo, "basefoo"); eq(rawget(d, "foo"), nil)
local d2 = setmetatable({}, {__index = d}); eq(d2.foo, "basefoo")
local f = setmetatable({}, {__index = function(t, k) return k .. "!" end}); eq(f.hi, "hi!"); eq(f[1], "1!")
local log = {}
local w = setmetatable({}, {__newindex = function(t, k, v) rawset(t, k, v * 2) end})
w.a = 5; eq(w.a, 10); w.a = 7; eq(w.a, 7)
local store = {}
local p = setmetatable({}, {__newindex = store}); p.k = 1; eq(rawget(p, "k"), nil); eq(store.k, 1)
-- inheritance
local Animal = {}; Animal.__index = Animal
function Animal.new(name) return setmetatable({name = name}, Animal) end
function Animal:speak() return self.name .. " makes a sound" end
local Dog = setmetatable({}, {__index = Animal}); Dog.__index = Dog
function Dog.new(name) local o = Animal.new(name); return setmetatable(o, Dog) end
function Dog:speak() return self.name .. " barks" end
eq(Dog.new("Rex"):speak(), "Rex barks"); eq(Animal.new("Cat"):speak(), "Cat makes a sound")
-- __metatable
local prot = setmetatable({}, {__metatable = "locked"})
eq(getmetatable(prot), "locked")
eq(err("setmetatable(..., {})", prot), "c:1: cannot change a protected metatable")
-- __name in messages
local named = setmetatable({}, {__name = "MyType"})
eq(err("return ... < 1", named), "c:1: attempt to compare MyType with number")
eq(err("local a = ... return a + 1", named), "c:1: attempt to perform arithmetic on a MyType value (local 'a')")
-- __tostring non-string
local bad = setmetatable({}, {__tostring = function() return {} end})
eq(err("return tostring(...)", bad), "c:1: '__tostring' must return a string")
-- __pairs
local pp = setmetatable({}, {__pairs = function(t) return function(_, k) if not k then return 1, "one" end end, t, nil end})
local seen = 0; for k, v in pairs(pp) do seen = seen + 1; eq(v, "one") end; eq(seen, 1)
-- __eq only for same types, result coerced to boolean
local e1 = setmetatable({}, {__eq = function() return 1 end})
eq(e1 == setmetatable({}, getmetatable(e1)), true); eq(e1 == 1, false); eq(e1 == e1, true)
-- __lt for mixed operand types
local lt = setmetatable({}, {__lt = function(a, b) return true end, __le = function() return false end})
eq(lt < 1, true); eq(1 < lt, true); eq(lt <= 1, false)
-- __index with rawget/rawset/rawequal/rawlen
local ri = setmetatable({1, 2, 3}, {__index = function() return "dflt" end, __len = function() return 99 end})
eq(ri[10], "dflt"); eq(rawget(ri, 10), nil); eq(#ri, 99); eq(rawlen(ri), 3); eq(rawequal(ri, ri), true)
eq(rawset(ri, 10, "x"), ri); eq(ri[10], "x")
-- __call chain and arguments
local c1 = setmetatable({}, {__call = function(self, ...) return select('#', ...), ... end})
eq(c1(), 0); eq((c1(1, 2)), 2)
local c2 = setmetatable({}, {__call = c1}); eq((c2(5)), 2)  -- c1 is called with (c2, 5)
eq(err("local t = {} t()"), "c:1: attempt to call a table value (local 't')")
-- metamethods returning several values are truncated
local mv = setmetatable({}, {__add = function() return 1, 2 end, __index = function() return 7, 8 end})
local r = {mv + 1}; eq(#r, 1); r = {mv.x}; eq(#r, 1)
-- __concat / __len / __unm on non-table operands and result values
local cc = setmetatable({}, {__concat = function(a, b) return (type(a) == "table" and "T" or a) .. (type(b) == "table" and "T" or b) end})
eq("a" .. cc .. "b", "aTb")
-- __gc and __mode accepted
setmetatable({}, {__gc = function() end, __mode = "k"})
-- __close receives the error
local got
do
  local ok = pcall(function() local x <close> = setmetatable({}, {__close = function(_, e) got = e end}); error("E", 0) end)
end
eq(got, "E")
-- __newindex on missing key only, __index on missing key only
local cnt = 0
local only = setmetatable({present = 1}, {__newindex = function() cnt = cnt + 1 end})
only.present = 2; only.absent = 1; eq(cnt, 1); eq(only.present, 2)
-- setmetatable returns table; bad args
eq(err("setmetatable(1, {})"), "c:1: bad argument #1 to 'setmetatable' (table expected, got number)")
eq(err("setmetatable({}, 1)"), "c:1: bad argument #2 to 'setmetatable' (nil or table expected, got number)")
eq(getmetatable({}), nil); eq(setmetatable(setmetatable({}, {}), nil) ~= nil, true)
-- error messages with variable info
eq(err("local t = {} return t.x.y"), "c:1: attempt to index a nil value (field 'x')")
eq(err("return undefinedvar.x"), "c:1: attempt to index a nil value (global 'undefinedvar')")
eq(err("undefinedfn()"), "c:1: attempt to call a nil value (global 'undefinedfn')")
eq(err("local t = {} t.m()"), "c:1: attempt to call a nil value (field 'm')")
eq(err("local t = {} t:m()"), "c:1: attempt to call a nil value (method 'm')")
eq(err("local u; local f = function() return u.x end; f()"), "c:1: attempt to index a nil value (upvalue 'u')")
eq(err("local a = {} return a .. 'x'"), "c:1: attempt to concatenate a table value (local 'a')")
eq(err("return 1 + nil"), "c:1: attempt to perform arithmetic on a nil value")
eq(err("local t = {} return t.a.b.c"), "c:1: attempt to index a nil value (field 'a')")
eq(err("return #5"), "c:1: attempt to get length of a number value")
eq(err("return -{}"), "c:1: attempt to perform arithmetic on a table value")
eq(err("local x = 5; x.y = 1"), "c:1: attempt to index a number value (local 'x')")
print("ok")
