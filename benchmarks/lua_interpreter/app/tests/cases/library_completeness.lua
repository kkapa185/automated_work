-- every function listed in the manual's library chapters exists; spot checks of the late additions
local expected = {
  _G = {"assert", "collectgarbage", "dofile", "error", "getmetatable", "ipairs", "load", "loadfile", "next", "pairs", "pcall",
        "print", "rawequal", "rawget", "rawlen", "rawset", "require", "select", "setmetatable", "tonumber", "tostring",
        "type", "warn", "xpcall"},
  coroutine = {"close", "create", "isyieldable", "resume", "running", "status", "wrap", "yield"},
  debug = {"debug", "gethook", "getinfo", "getlocal", "getmetatable", "getregistry", "getupvalue", "getuservalue",
           "sethook", "setlocal", "setmetatable", "setupvalue", "setuservalue", "traceback", "upvalueid", "upvaluejoin"},
  io = {"close", "flush", "input", "lines", "open", "output", "popen", "read", "tmpfile", "type", "write"},
  math = {"abs", "acos", "asin", "atan", "ceil", "cos", "deg", "exp", "floor", "fmod", "frexp", "ldexp", "log", "max", "min",
          "modf", "rad", "random", "randomseed", "sin", "sqrt", "tan", "tointeger", "type", "ult"},
  os = {"clock", "date", "difftime", "execute", "exit", "getenv", "remove", "rename", "setlocale", "time", "tmpname"},
  package = {"loadlib", "searchpath"},
  string = {"byte", "char", "dump", "find", "format", "gmatch", "gsub", "len", "lower", "match", "pack", "packsize", "rep",
            "reverse", "sub", "unpack", "upper"},
  table = {"concat", "create", "insert", "move", "pack", "remove", "sort", "unpack"},
  utf8 = {"char", "codepoint", "codes", "len", "offset"},
}
for lib, names in pairs(expected) do
  local t = lib == "_G" and _G or _G[lib]
  assert(type(t) == "table", lib)
  for _, n in ipairs(names) do assert(type(t[n]) == "function", lib .. "." .. n) end
end
assert(math.pi and math.huge and math.maxinteger and math.mininteger and utf8.charpattern and package.path and package.cpath and package.config and package.loaded and package.preload and package.searchers)
-- math additions
assert(math.deg(math.pi) == 180.0 and math.rad(180) == math.pi and math.deg(0) == 0.0)
local m, e = math.frexp(8); assert(m == 0.5 and e == 4 and math.type(e) == "integer")
m, e = math.frexp(0); assert(m == 0 and e == 0)
m, e = math.frexp(-3); assert(m == -0.75 and e == 2)
assert(math.ldexp(0.5, 4) == 8.0 and math.ldexp(1, -1) == 0.5 and math.ldexp(3, 0) == 3.0)
-- table.create: preallocation hint only; result is an ordinary empty table
local tc = table.create(10, 5); assert(type(tc) == "table" and #tc == 0 and next(tc) == nil)
tc[1] = "x"; assert(#tc == 1 and #table.create(0) == 0)
assert(select(2, pcall(table.create, -1)) == "bad argument #1 to 'create' (out of range)")
-- os.execute
assert(os.execute() == true)
local ok, how, code = os.execute("exit 3"); assert(ok == nil and how == "exit" and code == 3)
ok, how, code = os.execute("true"); assert(ok == true and how == "exit" and code == 0)
ok, how, code = os.execute("kill -9 $$"); assert(ok == nil and how == "signal" and code == 9)
-- warn: control messages are ignored, argument checking
assert(warn("@off") == nil and warn("@on") == nil and warn("@unknown") == nil and warn("@off") == nil)
assert(select(2, pcall(warn)) == "bad argument #1 to 'warn' (string expected, got no value)")
assert(select(2, pcall(warn, "a", {})) == "bad argument #2 to 'warn' (string expected, got table)")
-- string.dump is not supported
assert(select(2, pcall(string.dump, print)) == "unable to dump given function")
-- debug additions
local up1, up2 = 1, 2
local function f1() return up1 end
local function f2() return up2 end
local function f3() return up1 end
assert(debug.upvalueid(f1, 1) == debug.upvalueid(f3, 1) and debug.upvalueid(f1, 1) ~= debug.upvalueid(f2, 1))
debug.upvaluejoin(f1, 1, f2, 1); assert(f1() == 2 and f3() == 1)
assert(select(2, pcall(debug.upvalueid, f1, 5)) == "bad argument #2 to 'upvalueid' (invalid upvalue index)")
local ud = io.stdout; assert(debug.setuservalue(ud, 5) == ud and debug.getuservalue(ud) == 5 and debug.getuservalue({}) == nil)
print("library_completeness ok")
