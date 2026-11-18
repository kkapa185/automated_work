local V = {}
V.__index = V
V.__add = function(a, b) return setmetatable({x = a.x + b.x, y = a.y + b.y}, V) end
V.__eq = function(a, b) return a.x == b.x and a.y == b.y end
V.__lt = function(a, b) return a.x < b.x end
V.__le = function(a, b) return a.x <= b.x end
V.__tostring = function(v) return "(" .. v.x .. "," .. v.y .. ")" end
V.__len = function() return 2 end
V.__call = function(self, k) return self[k] end
V.__concat = function(a, b) return tostring(a) .. "&" .. tostring(b) end
V.__unm = function(a) return setmetatable({x = -a.x, y = -a.y}, V) end
local function new(x, y) return setmetatable({x = x, y = y}, V) end
local a, b = new(1, 2), new(3, 4)
print(tostring(a + b), a == new(1, 2), a < b, a <= b, #a, a("y"), a .. b, tostring(-a))
local log = {}
local proxy = setmetatable({}, {__newindex = function(t, k, v) log[#log + 1] = k; rawset(t, k, v) end})
proxy.a = 1; proxy.b = 2; proxy.a = 3; print(table.concat(log, ","), proxy.a)
local Animal = {} Animal.__index = Animal
function Animal.new(name) return setmetatable({name = name}, Animal) end
function Animal:speak() return self.name .. " makes a sound" end
local Dog = setmetatable({}, {__index = Animal}) Dog.__index = Dog
function Dog.new(name) local d = Animal.new(name) return setmetatable(d, Dog) end
function Dog:speak() return self.name .. " barks; " .. Animal.speak(self) end
print(Dog.new("Rex"):speak(), getmetatable("x").__index == string)
do local x <close> = setmetatable({}, {__close = function() print("closed") end}) print("in block") end
