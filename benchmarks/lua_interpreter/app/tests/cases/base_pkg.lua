-- R14/R21/R22: base library, package/require, debug
local function err(f, ...) local ok, e = pcall(f, ...); assert(not ok); return e end
-- type / tostring / tonumber / select / raw*
assert(err(type) == "bad argument #1 to 'type' (value expected)")
assert(tostring(12) == "12" and tostring(1.5) == "1.5" and tostring("s") == "s" and tostring(nil) == "nil" and tostring(false) == "false")
assert(tostring(print):find("^function: ") and tostring({}):find("^table: 0x") and tostring(coroutine.create(print)):find("^thread: 0x"))
assert(tonumber("  10  ") == 10 and tonumber("10", 16) == 16 and tonumber("7fffffffffffffff", 16) == math.maxinteger and tonumber("-ff", 16) == -255)
assert(tonumber("1e1") == 10.0 and tonumber("0x10") == 16 and tonumber(5) == 5 and tonumber(true) == nil and tonumber("1_0") == nil)
assert(err(tonumber) == "bad argument #1 to 'tonumber' (value expected)")
assert(err(tonumber, 10, 10) == "bad argument #1 to 'tonumber' (string expected, got number)")
assert(err(tonumber, "10", 99) == "bad argument #2 to 'tonumber' (base out of range)")
assert(select('#') == 0 and select('#', nil, nil) == 2 and select(2, "a", "b", "c") == "b" and select(-1, "a", "b", "c") == "c")
assert(select('#', select(2, "a", "b", "c")) == 2 and select('#', select(4, "a", "b", "c")) == 0 and select(-3, "a", "b", "c") == "a")
assert(err(select, 0) == "bad argument #1 to 'select' (index out of range)")
assert(err(select, -4, "a", "b", "c") == "bad argument #1 to 'select' (index out of range)")
assert(rawequal("a", "a") and not rawequal({}, {}) and rawlen({1, 2}) == 2 and rawlen("abc") == 3 and rawget({5}, 1) == 5)
assert(err(rawlen, 5) == "bad argument #1 to 'rawlen' (table or string expected)")
assert(err(rawset, 1, 2, 3) == "bad argument #1 to 'rawset' (table expected, got number)")
local rs = rawset({}, "k", "v"); assert(rs.k == "v")
-- ipairs / pairs / next
local seen = 0; for i, v in ipairs({1, 2, 3, nil, 5}) do seen = seen + 1 end; assert(seen == 3)
local px = setmetatable({}, {__index = function(_, i) if i <= 3 then return i * 2 end end})
local sum = 0; for i, v in ipairs(px) do sum = sum + v end; assert(sum == 12)
assert(err(ipairs) == "bad argument #1 to 'ipairs' (value expected)" and err(pairs) == "bad argument #1 to 'pairs' (value expected)")
assert(select(2, pcall(load("for k in pairs(nil) do end", "=c"))) == "c:1: bad argument #1 to 'for iterator' (table expected, got nil)")
assert(select(2, pcall(load("local t = ipairs(nil); for i in ipairs(nil) do end", "=c"))) == "c:1: attempt to index a nil value")
local order = {}; for k, v in pairs({10, 20, 30, a = 1}) do order[#order + 1] = tostring(k) end
assert(order[1] == "1" and order[2] == "2" and order[3] == "3" and order[4] == "a")
-- getmetatable / setmetatable
assert(getmetatable({}) == nil and getmetatable("x").__index == string and getmetatable(1) == nil)
local mt = {}; local obj = setmetatable({}, mt); assert(getmetatable(obj) == mt and setmetatable(obj, nil) == obj and getmetatable(obj) == nil)
assert(err(setmetatable, {}, 1) == "bad argument #2 to 'setmetatable' (nil or table expected, got number)")
assert(err(setmetatable, 1, {}) == "bad argument #1 to 'setmetatable' (table expected, got number)")
-- load: strings, functions, env, mode, chunknames
assert(load("return 1 + 1")() == 2)
local parts = {"return ", "40 ", "+ 2"}; local pi = 0
assert(load(function() pi = pi + 1; return parts[pi] end)() == 42)
assert(load("x = 1; return x", "=name", "t", {})() == 1)
local env = {}; load("y = 5", "=c", "t", env)(); assert(env.y == 5 and y == nil)
assert(load("return ...", "=c")(1, 2) == 1)
local f, e = load("return 1 +", "=name"); assert(f == nil and e == "name:1: unexpected symbol near <eof>")
f, e = load("x = ", "@file.lua"); assert(f == nil and e == "file.lua:1: unexpected symbol near <eof>")
f, e = load("x = ", "some code"); assert(f == nil and e == '[string "some code"]:1: unexpected symbol near <eof>')
f, e = load("x = \n\n 1 1", "line1\nline2"); assert(f == nil and e == '[string "line1..."]:3: unexpected symbol near \'1\'', e)
f, e = load("return 1", "=c", "b"); assert(f == nil and e == "attempt to load a text chunk (mode is 'b')")
f, e = load(function() return 1 end); assert(f == nil)
assert(load("return 1", nil, nil, nil) ~= nil)
assert(select(2, load("local a <const> = 1; a = 2", "=c")) == "c:1: attempt to assign to const variable 'a'")
assert(err(load) == "bad argument #1 to 'load' (function expected, got no value)")
-- dofile / loadfile
assert(dofile("tests/fixtures/mymod.lua").add(1, 2) == 3)
local lf = loadfile("tests/fixtures/mymod.lua"); assert(lf("N", "D").name == "N" and lf("N", "D").loaded_from == "D")
local nf, ne = loadfile("tests/fixtures/none.lua"); assert(nf == nil and ne == "cannot open tests/fixtures/none.lua")
nf, ne = loadfile("tests/fixtures/badsyntax.lua"); assert(nf == nil and ne == "tests/fixtures/badsyntax.lua:1: unexpected symbol near '='")
assert(err(dofile, "tests/fixtures/none.lua") == "cannot open tests/fixtures/none.lua")
assert(loadfile("tests/fixtures/mymod.lua", "t", {select = select}) ~= nil)
-- require / package
assert(type(package.path) == "string" and package.path:find("./?.lua", 1, true) and type(package.cpath) == "string" and package.config:sub(1, 1) == "/")
assert(package.loaded.string == string and package.loaded._G == _G and package.loaded.table == table and package.loaded.package == package)
package.path = "./tests/fixtures/?.lua;./tests/fixtures/?/init.lua"
local m, extra = require("mymod"); assert(m.add(2, 3) == 5 and m.name == "mymod" and extra == "./tests/fixtures/mymod.lua" and m.loaded_from == "./tests/fixtures/mymod.lua")
assert(require("mymod") == m and package.loaded.mymod == m)
package.loaded.mymod = nil; assert(require("mymod") ~= m)
local pk = require("pkg"); assert(pk.kind == "init" and pk.args[1] == "pkg")
require("sub_mod"); require("sub_mod"); assert(GLOBAL_SET_BY_MODULE == 1 and package.loaded.sub_mod == true)
package.preload.virtual = function(name, arg) return {n = name, a = arg} end
local v = require("virtual"); assert(v.n == "virtual" and v.a == ":preload:")
local e1 = err(require, "no_such_module")
assert(e1 == "module 'no_such_module' not found:\n\tno field package.preload['no_such_module']\n\tno file './tests/fixtures/no_such_module.lua'\n\tno file './tests/fixtures/no_such_module/init.lua'", e1)
assert(err(require, "badsyntax") == "error loading module 'badsyntax' from file './tests/fixtures/badsyntax.lua':\n\t./tests/fixtures/badsyntax.lua:1: unexpected symbol near '='")
assert(package.searchpath("mymod", package.path) == "./tests/fixtures/mymod.lua")
local sp, spmsg = package.searchpath("zzz.yyy", "./?.lua;/x/?.lua"); assert(sp == nil and spmsg == "no file './zzz/yyy.lua'\n\tno file '/x/zzz/yyy.lua'")
assert(package.searchpath("a.b", "?", ".", "_") == nil and select(2, package.searchpath("a.b", "?", ".", "_")) == "no file 'a_b'")
package.preload.nilmod = function() end; assert(require("nilmod") == true)
package.preload.errmod = function() error("boom", 0) end; assert(err(require, "errmod") == "boom")
-- debug
assert(debug.traceback("msg"):find("^msg\nstack traceback:\n\t") and debug.traceback(nil):find("^stack traceback:") and debug.traceback(12):find("^12\nstack"))
local tbt = {}; assert(debug.traceback(tbt) == tbt)
local function lvl1() return debug.traceback("here", 1) end
local tb = lvl1(); assert(tb:find("^here\nstack traceback:\n\t[^\n]*in ") and tb:find("in main chunk"))
local info = debug.getinfo(1, "Sl"); assert(info.short_src == "tests/cases/base_pkg.lua" and info.source == "@tests/cases/base_pkg.lua" and info.what == "main" and info.currentline == 81)
local function fn(a, b, ...) return debug.getinfo(1, "nSlutf") end
local fi = fn(); assert(fi.what == "Lua" and fi.nparams == 2 and fi.isvararg == true and fi.func == fn and fi.name == "fn" and fi.namewhat == "local" and fi.linedefined == fi.lastlinedefined and fi.nups >= 0)
local pi2 = debug.getinfo(print); assert(pi2.what == "C" and pi2.short_src == "[C]" and pi2.currentline == -1 and pi2.source == "=[C]")
assert(debug.getinfo(100) == nil and debug.getinfo(0, "n").name == "getinfo")
assert(err(debug.getinfo, 1, "X") == "bad argument #2 to 'getinfo' (invalid option)")
local up1 = 10; local function useup() return up1 end
assert(debug.getupvalue(useup, 1) == "up1" and select(2, debug.getupvalue(useup, 1)) == 10 and debug.setupvalue(useup, 1, 20) == "up1" and useup() == 20)
assert(debug.getmetatable("").__index == string and debug.getregistry() ~= nil and debug.gethook() == nil)
debug.sethook(); assert(debug.setmetatable({}, nil) ~= nil)
local co = coroutine.create(function() local x = 1; coroutine.yield() end); coroutine.resume(co)
assert(debug.traceback(co):find("^stack traceback:") and debug.traceback(co, "m"):find("^m\nstack"))
-- xpcall with traceback handler
local ok, tr = xpcall(function() error("E") end, debug.traceback)
assert(not ok and tr:find("^tests/cases/base_pkg.lua:%d+: E\nstack traceback:\n"))
-- collectgarbage return values
assert(collectgarbage("collect") == 0 and type(collectgarbage("count")) == "number" and collectgarbage() == 0)
-- _VERSION / _G
assert(_VERSION == "Lua 5.5" and _G._G == _G)
print("base_pkg ok")
-- review fixes: C functions print like other functions; deprecated functions are absent in 5.5
assert(tostring(print):find("^function: 0x") and not tostring(print):find("builtin"))
assert(math.pow == nil and math.cosh == nil and string.gfind == nil and table.getn == nil and unpack == nil and loadstring == nil)
