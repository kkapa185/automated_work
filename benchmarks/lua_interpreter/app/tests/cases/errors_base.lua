dofile("tests/cases/prelude.lua")
-- R11 error / pcall / xpcall
local function thrower(level) error("msg", level) end
eq(select(2, pcall(thrower, 0)), "msg")
eq(select(2, pcall(thrower)), "tests/cases/errors_base.lua:3: msg")
eq(select(2, pcall(thrower, 1)), "tests/cases/errors_base.lua:3: msg")
local function caller() thrower(2) end   
eq(select(2, pcall(caller)), "tests/cases/errors_base.lua:7: msg")
eq(select(2, pcall(error, "m")), "m")
local tbl = {}
local ok, e = pcall(error, tbl); eq(ok, false); eq(e, tbl)
ok, e = pcall(error); eq(e, nil)
ok, e = pcall(error, 42); eq(e, 42)
eq(select('#', pcall(function() return 1, 2, 3 end)), 4)
eq(pcall(function(...) return ... end, "a", "b"), true)
-- assert
eq(select(2, pcall(assert, false, "custom")), "custom")
eq(err("assert(false)"), "c:1: assertion failed!")
eq(err("assert(nil, 'x')"), "x")
local errobj = {}
eq(select(2, pcall(assert, false, errobj)), errobj)
eq(select('#', assert(1, 2, 3)), 3)
eq(err("assert()"), "c:1: bad argument #1 to 'assert' (value expected)")
-- xpcall
local handled
local ok3, r3 = xpcall(function() error("oops", 0) end, function(m) handled = m; return "handled:" .. m end)
eq(ok3, false); eq(r3, "handled:oops"); eq(handled, "oops")
eq(select('#', xpcall(function(a, b) return a, b end, print, 1, 2)), 3)
ok3, r3 = xpcall(function() local x = nil; return x.f end, function(m) return "H " .. m end)
eq(r3, "H tests/cases/errors_base.lua:29: attempt to index a nil value (local 'x')")
-- error in handler
ok3 = xpcall(function() error("a") end, function() error("b") end); eq(ok3, false)
-- nested pcall
eq(pcall(pcall, error, "x"), true)
local o1, o2, o3 = pcall(pcall, error, "x"); eq(o2, false); eq(o3, "x")
-- runtime error inside deep call keeps position
local function lvl3() local t = nil; return t.x end
local function lvl2() return (lvl3()) end
eq(select(2, pcall(lvl2)), "tests/cases/errors_base.lua:37: attempt to index a nil value (local 't')")
-- syntax errors
eq(cerr("x = "), "c:1: unexpected symbol near <eof>")
eq(cerr("x = = 1"), "c:1: unexpected symbol near '='")
eq(cerr("for"), "c:1: <name> expected near <eof>")
eq(cerr("if x then"), "c:1: 'end' expected near <eof>")
eq(cerr("if x then\n\nfoo()"), "c:3: 'end' expected (to close 'if' at line 1) near <eof>")
eq(cerr("x = 'abc"), "c:1: unfinished string near <eof>")
eq(cerr("x = 'abc\ny'"), "c:1: unfinished string near ''abc'")
eq(cerr("x = [[abc"), "c:1: unfinished long string (starting at line 1) near <eof>")
eq(cerr("goto nowhere"), "c:1: no visible label 'nowhere' for goto at line 1")
eq(cerr("break"), "c:1: break outside a loop at line 1")
eq(cerr("::a:: ::a::"), "c:1: label 'a' already defined on line 1")
eq(cerr("x = 3x"), "c:1: malformed number near '3x'")
eq(cerr("x = '\\q'"), "c:1: invalid escape sequence near ''\\q'")
eq(cerr("local function f() return ... end"), "c:1: cannot use '...' outside a vararg function near '...'")
eq(cerr("f() = 1"), "c:1: syntax error near '='")
eq(cerr("x = }"), "c:1: unexpected symbol near '}'")
eq(cerr("return return"), "c:1: unexpected symbol near 'return'")
eq(cerr("local x <close>, y <close> = 1, 2"), "c:1: multiple to-be-closed variables in local list")
-- line numbers in multi-line chunks
eq(err("local x = 1\nlocal y = 2\nreturn nil + y"), "c:3: attempt to perform arithmetic on a nil value")
eq(err("\n\n\nerror('deep')"), "c:4: deep")
eq(err("error('lvl2', 2)"), "lvl2")
-- load
local f = load("return 1 + 1"); eq(f(), 2)
eq(load("syntax error here"), nil)
local lf, lm = load("x ="); eq(lf, nil); eq(lm, "[string \"x =\"]:1: unexpected symbol near <eof>")
local env = {y = 5}
f = load("x = y; return x", "chunk", "t", env); eq(f(), 5); eq(env.x, 5); eq(x, nil)
f = load("return ...", "=name"); eq((f(7)), 7)
local parts = {"return ", "4", "2"}; local pi = 0
f = load(function() pi = pi + 1; return parts[pi] end); eq(f(), 42)
eq(select(2, pcall(load("error('e')", "=my"))), "my:1: e")
eq(select(2, pcall(load("error('e')", "@file.lua"))), "file.lua:1: e")
eq(select(2, pcall(load("error('e')", "line1\nline2"))), "[string \"line1...\"]:1: e")
eq(load("return 1", "x", "b"), nil)
-- _ENV
local function withenv() local _ENV = {z = 9}; return z end; eq(withenv(), 9)
local function penv(_ENV) return a end; eq(penv({a = 3}), 3)
eq(_G._G, _G); eq(_VERSION, "Lua 5.4"); eq(_ENV, _G)
gvar = 5; eq(_G.gvar, 5); _G.gvar2 = 6; eq(gvar2, 6)
-- select / tostring / type / ipairs / misc
eq(select(2, "a", "b", "c"), "b"); eq(select('#'), 0)
eq(err("select(0)"), "c:1: bad argument #1 to 'select' (index out of range)")
eq(type(nil), "nil"); eq(type(print), "function"); eq(type({}), "table"); eq(type("s"), "string"); eq(type(2), "number")
eq(err("type()"), "c:1: bad argument #1 to 'type' (value expected)")
eq(tostring(nil), "nil"); eq(tostring(true), "true"); eq(tostring(false), "false")
local ts = tostring({}); eq(ts == tostring({}), false)
eq(err("for i in ipairs() do end"), "c:1: bad argument #1 to 'ipairs' (value expected)")
eq(err("for k in pairs(nil) do end"), "c:1: bad argument #1 to 'for iterator' (table expected, got nil)")
eq(err("rawset({}, nil, 1)"), "c:1: index is nil")
eq(err("rawlen(5)"), "c:1: bad argument #1 to 'rawlen' (table or string expected)")
eq(collectgarbage("count") > 0, true); eq(collectgarbage(), 0); eq(collectgarbage("step") ~= nil, true)
-- require
package.path = "tests/modules/?.lua;tests/modules/?/init.lua;" .. package.path
local m = require("mymod"); eq(m.hello(), "hello from mymod"); eq(m.name, "mymod")
eq(require("mymod"), m); eq(package.loaded.mymod, m)
local pk = require("pkg"); eq(pk.init, true)
package.preload.virtual = function(name, extra) return {n = name, x = extra} end
eq(require("virtual").n, "virtual")
local nf = select(2, pcall(require, "does.not.exist"))
eq(type(nf), "string")
-- goto may not jump into the scope of a local (unless the label ends the block)
eq(cerr("goto f; local x; ::f:: print(x)"), "c:1: <goto f> at line 1 jumps into the scope of local 'x'")
eq(type(load("goto f; local x; ::f::")), "function")
eq(type(load("do goto f; local x; ::f:: end")), "function")
eq(type(load("local x ::top:: x = 1 goto top")), "function")
eq(type(load("for i = 1, 2 do local y; if i then goto continue end; local z; ::continue:: end")), "function")
print("ok")
