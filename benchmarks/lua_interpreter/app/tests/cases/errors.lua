-- R11 (core part): pcall/error/messages with position information
local function err(src, env) local f = assert(load(src, "=c", "t", env or _G)); local ok, e = pcall(f); assert(not ok); return e end
assert(err("local x; x.y = 1") == "c:1: attempt to index a nil value (local 'x')")
assert(err("local x; return x.y") == "c:1: attempt to index a nil value (local 'x')")
assert(err("return undefinedvar.y") == "c:1: attempt to index a nil value (global 'undefinedvar')")
assert(err("local t = {}; return t.a.b") == "c:1: attempt to index a nil value (field 'a')")
assert(err("local t = {}; t.a.b = 1") == "c:1: attempt to index a nil value (field 'a')")
assert(err("undefinedfn()") == "c:1: attempt to call a nil value (global 'undefinedfn')")
assert(err("local t = {}; t.m()") == "c:1: attempt to call a nil value (field 'm')")
assert(err("local t = {}; t:m()") == "c:1: attempt to call a nil value (method 'm')")
assert(err("local f; f()") == "c:1: attempt to call a nil value (local 'f')")
assert(err("local f; (function() f() end)()") == "c:1: attempt to call a nil value (upvalue 'f')")
assert(err("(1)()") == "c:1: attempt to call a number value")
assert(err("local a = {} ; return a + 1") == "c:1: attempt to perform arithmetic on a table value (local 'a')")
assert(err("local a; return 1 + a") == "c:1: attempt to perform arithmetic on a nil value (local 'a')")
assert(err("local t = {}; return t.x * 2") == "c:1: attempt to perform arithmetic on a nil value (field 'x')")
assert(err("return -{}") == "c:1: attempt to perform arithmetic on a table value")
assert(err("local s = {}; return 'a' .. s") == "c:1: attempt to concatenate a table value (local 's')")
assert(err("local s; return s .. 'a'") == "c:1: attempt to concatenate a nil value (local 's')")
assert(err("return 1 < 'x'") == "c:1: attempt to compare number with string")
assert(err("return {} < {}") == "c:1: attempt to compare two table values")
assert(err("return nil < 1") == "c:1: attempt to compare nil with number")
assert(err("return #5") == "c:1: attempt to get length of a number value")
assert(err("local n = nil; return #n") == "c:1: attempt to get length of a nil value (local 'n')")
assert(err("return 1.5 | 1") == "c:1: number has no integer representation")
assert(err("return {} | 1") == "c:1: attempt to perform bitwise operation on a table value")
assert(err("return 2^63 | 0") == "c:1: number has no integer representation")
assert(err("\n\n  local x = nil + 1") == "c:3: attempt to perform arithmetic on a nil value")
-- error() values and levels
local ok, e = pcall(error, "msg", 0); assert(not ok and e == "msg")
ok, e = pcall(error); assert(not ok and e == nil)
ok, e = pcall(error, nil); assert(not ok and e == nil)
local obj = {}; ok, e = pcall(error, obj); assert(not ok and e == obj)
ok, e = pcall(error, 42); assert(not ok and e == 42)
assert(err("error('boom')") == "c:1: boom")
assert(err("error('boom', 1)") == "c:1: boom")
assert(err("error('boom', 0)") == "boom")
assert(err("local function f() error('lvl2', 2) end\n\nf()") == "c:3: lvl2")
assert(err("local function f() error('lvl1') end\n\nf()") == "c:1: lvl1")
assert(err("error({code = 1})").code == 1)
assert(err("error(setmetatable({}, {__tostring = function() return 'custom' end}))") ~= nil)
-- assert
ok, e = pcall(assert, false); assert(not ok and e == "assertion failed!")
ok, e = pcall(assert, nil, "custom msg"); assert(not ok and e == "custom msg")
ok, e = pcall(assert, false, obj); assert(not ok and e == obj)
assert(select('#', assert(1, 2, 3)) == 3 and assert("v") == "v")
-- pcall / xpcall return values
assert(select('#', pcall(function() return 1, 2, 3 end)) == 4)
local a, b, c = pcall(function(...) return ... end, "x", "y"); assert(a == true and b == "x" and c == "y")
ok, e = xpcall(function() error("E", 0) end, function(m) return "handled:" .. m end)
assert(not ok and e == "handled:E")
a, b = xpcall(function(x, y) return x + y end, print, 3, 4); assert(a == true and b == 7)
ok, e = xpcall(function() local x = nil; return x.f end, function(m) return m end)
assert(type(e) == "string")
-- nested pcall; error in handler
ok, e = pcall(pcall, error, "x"); assert(ok == true and e == false)
ok, e = pcall(function() local ok, e = pcall(error, "inner"); error("outer:" .. tostring(e), 0) end); assert(e == "outer:inner")
-- stack overflow caught; interpreter still usable
local function so() return 1 + so() end
ok, e = pcall(so); assert(not ok and type(e) == "string")
local depth = 0
local function so2() depth = depth + 1; so2() end
ok, e = pcall(so2); assert(not ok and depth > 1000)
-- errors in metamethods propagate; tostring error
ok, e = pcall(tostring, setmetatable({}, {__tostring = function() return {} end})); assert(not ok)
-- runtime errors carry correct line for multi-line statements
assert(err("local t = {}\nlocal x = 1 +\n  t.a.b") == "c:3: attempt to index a nil value (field 'a')")
print("errors ok")
-- parser nesting limit is an error, not a crash (R26)
local code = "return "
for i = 1, 1000 do code = code .. "(" end
code = code .. "1"
for i = 1, 1000 do code = code .. ")" end
local f, msg = load(code, "=c")
assert(f == nil and msg == "c:1: chunk has too many syntax levels", msg)
local code2 = ""
for i = 1, 1000 do code2 = code2 .. "do " end
f, msg = load(code2, "=c"); assert(f == nil and msg == "c:1: chunk has too many syntax levels", msg)
-- error levels through several functions
local function run(level) local f = assert(load("local lvl = " .. level .. "\nlocal function f(l) error('m', l) end\nlocal function g(l) f(l) end\ng(lvl)\n", "=c")); local ok, e = pcall(f); return e end
assert(run(0) == "m" and run(1) == "c:2: m" and run(2) == "c:3: m" and run(3) == "c:4: m")
-- xpcall: handler sees the original error value, runs at the error point; handler errors do not hang
ok, e = xpcall(load("local t = nil; return t.x", "=c"), function(m) return "H:" .. m end)
assert(not ok and e == "H:c:1: attempt to index a nil value (local 't')", e)
local seen
ok, e = xpcall(function() error({1, 2}) end, function(m) seen = m; return "x" end)
assert(not ok and type(seen) == "table" and seen[2] == 2 and e == "x")
ok, e = xpcall(function() error("a") end, function(m) error("handler broke") end)
assert(ok == false)
ok, e = xpcall(error, function(m) return m end, "direct", 0); assert(not ok and e == "direct")
assert(select('#', xpcall(function(...) return ... end, print, 1, nil, 3)) == 4)
ok, e = pcall(xpcall); assert(not ok and e == "bad argument #2 to 'xpcall' (function expected, got no value)", e)
-- errors in __index / __newindex / __call metamethods carry their own positions
assert(err("local bad = setmetatable({}, {__index = function(t, k) error('idx:' .. k) end})\nreturn bad.zip") == "c:1: idx:zip")
assert(err("local bad = setmetatable({}, {__index = function(t, k) error('idx:' .. k, 2) end})\nreturn bad.zip") == "c:2: idx:zip")
assert(err("local bad = setmetatable({}, {__newindex = function(t, k) error('ni', 2) end})\n\nbad.x = 1") == "c:3: ni")
assert(err("local bad = setmetatable({}, {__call = function(t, k) error('cl', 2) end})\n\nbad()") == "c:3: cl")
-- error with non-string values keeps identity through nested pcall
local tag = {}
ok, e = pcall(function() local ok, e = pcall(error, tag); error(e) end); assert(e == tag)
-- tostring(nil) / concat error naming
assert(err("local a = 'x' .. nil") == "c:1: attempt to concatenate a nil value")
assert(err("local t = {}; return t.name .. 'x'") == "c:1: attempt to concatenate a nil value (field 'name')")
assert(err("return 1 + 'a'") == "c:1: attempt to perform arithmetic on a string value (constant 'a')")
assert(err("local a <const> = nil; return a.b") == "c:1: attempt to index a nil value (local 'a')")
assert(err("local m = {}; return m.nofunc()") == "c:1: attempt to call a nil value (field 'nofunc')")
assert(err("local up = nil; local function f() return up.x end; return f()") == "c:1: attempt to index a nil value (upvalue 'up')")
