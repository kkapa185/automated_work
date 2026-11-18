dofile("tests/cases/prelude.lua")
-- R18 os
eq(type(os.time()), "number"); eq(math.type(os.time()), "integer"); eq(type(os.clock()), "number"); eq(os.clock() >= 0, true)
eq(os.date("!%Y-%m-%d %H:%M:%S", 0), "1970-01-01 00:00:00"); eq(os.date("!%Y-%m-%d %H:%M:%S", 86400 * 365), "1971-01-01 00:00:00")
eq(os.date("!%A %B %d %j %p %y", 0), "Thursday January 01 001 AM 70"); eq(os.date("!%a %b %e", 0), "Thu Jan  1")
eq(os.date("!%c", 0), "Thu Jan  1 00:00:00 1970"); eq(os.date("!%x %X", 3661), "01/01/70 01:01:01"); eq(os.date("!%I:%M %p", 13 * 3600), "01:00 PM")
eq(os.date("!%D %F %T %R", 0), "01/01/70 1970-01-01 00:00:00 00:00"); eq(os.date("!%%|%n|%t|", 0), "%|\n|\t|")
eq(os.date("!%H", 1e9 // 1), "01"); eq(os.date("!%w %u", 0), "4 4"); eq(os.date("!%U %W %V %G", 0), "00 00 01 1970")
local d = os.date("!*t", 86400 + 3661)
eq(d.year, 1970); eq(d.month, 1); eq(d.day, 2); eq(d.hour, 1); eq(d.min, 1); eq(d.sec, 1); eq(d.wday, 6); eq(d.yday, 2); eq(d.isdst, false)
eq(os.date("!*t", 951782400).month, 2); eq(os.date("!*t", 951782400).day, 29)    -- 2000-02-29 00:00:00 UTC
eq(err("os.date('%Q')"), "c:1: bad argument #1 to 'date' (invalid conversion specifier '%Q')")
local t0 = os.time{year = 2000, month = 1, day = 1, hour = 0}
eq(os.time{year = 2000, month = 1, day = 2, hour = 0} - t0, 86400)
eq(os.time{year = 2000, month = 1, day = 1, hour = 0, min = 90} - t0, 5400)
local norm = {year = 2001, month = 14, day = 35, hour = 12}
os.time(norm); eq(norm.year, 2002); eq(norm.month, 3); eq(norm.day, 7)
local back = os.date("*t", t0); eq(back.year, 2000); eq(back.month, 1); eq(back.day, 1); eq(back.hour, 0)
eq(os.time{year = 2000, month = 1, day = 1} - t0, 12 * 3600)
eq(err("os.time{year = 2000}"), "c:1: field 'month' missing in date table")
eq(err("os.time{year = 2000, month = 1.5, day = 1}"), "c:1: field 'month' is not an integer")
eq(os.difftime(10, 4), 6.0); eq(os.getenv("NO_SUCH_VAR_XYZ_123"), nil); eq(type(os.getenv("PATH")), "string")
-- files
local name = os.tmpname()
local f = assert(io.open(name, "w"))
eq(io.type(f), "file"); eq(io.type(42), nil); eq(f:write("line1\n", 2, " ", 3.5, "\nline3\n"), f)
eq(tostring(f):sub(1, 6), "file (")
eq(f:close(), true); eq(io.type(f), "closed file"); eq(tostring(f), "file (closed)")
eq(err("local f = io.open(..., 'r') f:close() f:read()", name), "c:1: attempt to use a closed file")
f = io.open(name, "r")
eq(f:read(), "line1"); eq(f:read("n"), 2); eq(f:read("n"), 3.5); eq(f:read("l"), ""); eq(f:read("L"), "line3\n"); eq(f:read(), nil); eq(f:read("a"), "")
eq(f:read(0), nil); f:close()
f = io.open(name); eq(f:read("a"), "line1\n2 3.5\nline3\n"); eq(f:seek("set", 0), 0); eq(f:read(3), "lin"); eq(f:seek("cur"), 3); eq(f:seek("end"), 18)
eq(f:seek("set", 2), 2); eq(f:read(1, 1), "n"); eq(f:read(0), "") ; f:close()
f = io.open(name); local l1, l2 = f:read("l", "L"); eq(l1, "line1"); eq(l2, "2 3.5\n"); f:close()
f = io.open(name); local a, b = f:read("*l", "*n"); eq(a, "line1"); eq(b, 2); f:close()
local lines = {}; for l in io.lines(name) do lines[#lines + 1] = l end; eq(#lines, 3); eq(lines[2], "2 3.5")
lines = {}; for a, b in io.lines(name, 1, 2) do lines[#lines + 1] = a .. b end; eq(lines[1], "lin"); eq(lines[2], "e1\n")
f = io.open(name); lines = {}; for l in f:lines("L") do lines[#lines + 1] = l end; eq(lines[3], "line3\n"); eq(io.type(f), "file"); f:close()
f = io.open(name, "a"); f:write("appended\n"); f:close()
lines = {}; for l in io.lines(name) do lines[#lines + 1] = l end; eq(#lines, 4); eq(lines[4], "appended")
f = io.open(name, "r+"); f:write("LINE"); f:seek("set", 0); eq(f:read("l"), "LINE1"); f:close()
f = io.open(name, "w+"); f:write("hello"); f:seek("set", 1); eq(f:read("a"), "ello"); f:close()
f = io.open(name, "rb"); eq(f:read("a"), "hello"); f:close()
local nf, nmsg, ncode = io.open("/nonexistent_dir_xyz/file.txt")
eq(nf, nil); eq(nmsg, "/nonexistent_dir_xyz/file.txt: No such file or directory"); eq(ncode, 2)
eq(err("io.open('x', 'z')"), "c:1: bad argument #2 to 'open' (invalid mode)")
eq(err("io.lines('/nonexistent_dir_xyz/f')"), "c:1: /nonexistent_dir_xyz/f: No such file or directory")
eq(select(2, io.open("/nonexistent_dir_xyz/f")), "/nonexistent_dir_xyz/f: No such file or directory")
eq(err("io.open('x'):nosuchmethod()") ~= nil, true)
-- default files
local out = io.output(); eq(out, io.stdout); eq(io.input(), io.stdin)
eq(io.write(""), io.stdout); eq(io.stdout:write(""), io.stdout); eq(io.stderr:write(""), io.stderr)
io.output(name); io.write("via default\n"); io.close(); io.output(io.stdout)
io.input(name); eq(io.read(), "via default"); eq(io.read(), nil); io.close(io.input()); io.input(io.stdin)
eq(err("io.write({})"), "c:1: bad argument #1 to 'write' (string expected, got table)")
eq(select(2, io.stdout:close()), "cannot close standard file")
-- 'for' closing value of io.lines
do
  local it, _, _, tbc = io.lines(name)
  eq(io.type(tbc), "file")
  for l in io.lines(name) do break end
end
-- remove / rename
local name2 = name .. ".moved"
eq(os.rename(name, name2), true); eq(io.open(name), nil); eq(os.remove(name2), true)
local rok, rmsg, rcode = os.remove(name2); eq(rok, nil); eq(rmsg, name2 .. ": No such file or directory"); eq(rcode, 2)
local tf = io.tmpfile(); tf:write("tmp"); tf:seek("set"); eq(tf:read("a"), "tmp"); tf:close()
-- R19 debug
local tb = debug.traceback("msg")
eq(tb:sub(1, 22), "msg\nstack traceback:\n\t"); eq(tb:find("os_io_debug.lua:%d+: in main chunk") ~= nil, true)
eq(debug.traceback(12):sub(1, 2), "12"); eq(type(debug.traceback()), "string"); eq(debug.traceback({}) ~= nil, true)
local tbt = {}; eq(debug.traceback(tbt), tbt)
local ln = debug.getinfo(1, "l").currentline
eq(debug.getinfo(1, "l").currentline, ln + 1)
local info = debug.getinfo(print); eq(info.what, "C"); eq(info.short_src, "[C]")
ln = debug.getinfo(1, "l").currentline
local function fdef() end
info = debug.getinfo(fdef); eq(info.what, "Lua"); eq(info.linedefined, ln + 1); eq(info.short_src, "tests/cases/os_io_debug.lua"); eq(info.source, "@tests/cases/os_io_debug.lua")
info = debug.getinfo(1); eq(info.what, "main"); eq(info.currentline > 0, true); eq(info.func ~= nil, true)
eq(debug.getinfo(100), nil); eq(debug.getinfo(0).what, "C")
local ok2, trace = xpcall(function() error("deep") end, debug.traceback)
eq(ok2, false); eq(trace:find("deep", 1, true) ~= nil, true); eq(trace:find("stack traceback:", 1, true) ~= nil, true)
local up1, up2 = 5, 6
local function useup() return up1 + up2 end
local un, uv = debug.getupvalue(useup, 1); eq(un, "up1"); eq(uv, 5); eq(debug.setupvalue(useup, 2, 10), "up2"); eq(useup(), 15)
eq(debug.getupvalue(useup, 9), nil); eq(debug.sethook(), nil); eq(debug.gethook(), nil)
eq(getmetatable("x").__index, string); eq(debug.getmetatable("x").__index, string)
local dt = setmetatable({}, {__index = {z = 1}}); eq(debug.getmetatable(dt).__index.z, 1)
debug.setmetatable(dt, nil); eq(getmetatable(dt), nil)
print("ok")
