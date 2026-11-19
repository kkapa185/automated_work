-- R8: Lua 5.5 declarations: global, <const>, <close>
local function cerr(src) local f, e = load(src, "=c"); assert(not f, "expected compile error"); return e end
local function rerr(src) local f = assert(load(src, "=c")); local ok, e = pcall(f); assert(not ok); return e end
-- const
assert(cerr("local x <const> = 1; x = 2") == "c:1: attempt to assign to const variable 'x'")
assert(cerr("local x <const>, y = 1, 2; y = 3; x = 3") == "c:1: attempt to assign to const variable 'x'")
assert(cerr("local <const> a, b = 1, 2; b = 3") == "c:1: attempt to assign to const variable 'b'")
assert(cerr("local x <const> = 1; local function f() x = 2 end") == "c:1: attempt to assign to const variable 'x'")
assert(cerr("local x <foo> = 1") == "c:1: unknown attribute 'foo'")
local K <const> = 10; assert(K == 10)
-- global declarations
assert(load("global X; X = 1; return X", "=c")() == 1)
assert(cerr("global Y; Z = 1") == "c:1: variable 'Z' not declared")
assert(cerr("do global Y; Y = 1; X = 1 end") == "c:1: variable 'X' not declared")
assert(load("X = 1; do global Y; Y = 1 end; X = 2; return X", "=c")() == 2)  -- manual example
assert(load("global<const> *; return print ~= nil", "=c")() == true)
assert(cerr("global<const> *; Y = 1") == "c:1: attempt to assign to const variable 'Y'")
assert(load("global X; global<const> *; X = 1; return X", "=c")() == 1)     -- manual example
assert(cerr("global X; global<const> *; Y = 1") == "c:1: attempt to assign to const variable 'Y'")
assert(cerr("global X <const>, _G; X = 1") == "c:1: attempt to assign to const variable 'X'")
assert(load("global X <const>, _G; _ENV.X = 1; return _G.X", "=c")() == 1)
assert(load("global *; Q = 3; return Q", "=c")() == 3)
assert(cerr("global none; print(1)") == "c:1: variable 'print' not declared")
assert(load("global print; print(1 == 1)", "=c") ~= nil)
-- global with initialisation: error if already defined
assert(rerr("G1 = 1; global G1 = 2") == "c:1: global 'G1' already defined")
assert(load("global G2 = 5; return G2", "=c")() == 5)
assert(load("global a, b = 1, 2; return a + b", "=c")() == 3)
assert(rerr("global function gf() end; global function gf() end") == "c:1: global 'gf' already defined")
assert(load("global function gf2() return 7 end; return gf2()", "=c")() == 7)
-- scoping of global decl inside functions
assert(cerr("global Y; local function f() return Zzz end") == "c:1: variable 'Zzz' not declared")
-- to-be-closed
local log = {}
local function closer(name) return setmetatable({}, {__close = function(_, e) log[#log + 1] = name .. ":" .. tostring(e) end}) end
do local a <close> = closer("a"); local b <close> = closer("b"); log[#log + 1] = "body" end
assert(#log == 3 and log[1] == "body" and log[2] == "b:nil" and log[3] == "a:nil")
log = {}
local function f() local a <close> = closer("fa"); return "ret", 2 end
local r1, r2 = f(); assert(r1 == "ret" and r2 == 2 and log[1] == "fa:nil")
log = {}
for i = 1, 3 do local c <close> = closer("it" .. i); if i == 2 then break end end
assert(#log == 2 and log[1] == "it1:nil" and log[2] == "it2:nil")
log = {}
local ok, e = pcall(function() local a <close> = closer("err"); error("boom", 0) end)
assert(not ok and e == "boom" and log[1] == "err:boom")
log = {}
do local n <close> = nil; local f2 <close> = false end   -- nil and false are allowed
assert(rerr("local x <close> = 42") == "c:1: variable 'x' got a non-closable value")
assert(cerr("local a <close>, b <close> = nil, nil") == "c:1: multiple to-be-closed variables in local list")
-- goto out of a block closes
log = {}
do
  local i = 0
  ::again:: do local c <close> = closer("g" .. i); i = i + 1; if i < 3 then goto again end end
end
assert(#log == 3)
-- generic for closing value (4th value)
log = {}
local function iter() return function(_, c) c = c + 1; if c <= 2 then return c end end, nil, 0, closer("forclose") end
for i in iter() do end
assert(#log == 1 and log[1] == "forclose:nil")
log = {}
for i in iter() do break end
assert(#log == 1)
-- error in __close replaces error
ok, e = pcall(function() local a <close> = setmetatable({}, {__close = function() error("in close", 0) end}); error("orig", 0) end)
assert(not ok and e == "in close")
print("declarations ok")
