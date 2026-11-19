#!/bin/sh
# R1/R2: command line behaviour. Expected outputs are derived from the specification, not from the implementation.
cd "$(dirname "$0")/../.." || exit 1
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail() { echo "CLI FAIL: $1"; exit 1; }

# arg table and varargs
cat > "$T/args.lua" <<'LUA'
print(arg[0], arg[1], arg[2], #arg, ...)
print(select('#', ...), arg[-1] ~= nil)
LUA
out=$(./lua "$T/args.lua" a b) || fail "args exit"
[ "$out" = "$T/args.lua	a	b	2	a	b
2	true" ] || fail "args output: $out"

# no extra args
out=$(./lua "$T/args.lua") || fail "noargs"
[ "$(echo "$out" | head -1)" = "$T/args.lua	nil	nil	0" ] || fail "noargs out: $out"

# normal exit status 0 and output
echo 'print("hi")' > "$T/ok.lua"
./lua "$T/ok.lua" > "$T/o" 2> "$T/e"; [ $? -eq 0 ] || fail "ok status"
[ "$(cat "$T/o")" = "hi" ] || fail "ok stdout"; [ ! -s "$T/e" ] || fail "ok stderr not empty"

# uncaught runtime error: stderr 'lua: msg', traceback, exit 1, stdout flushed before
printf 'print("before")\nlocal function f() error("boom") end\nf()\n' > "$T/err.lua"
./lua "$T/err.lua" > "$T/o" 2> "$T/e"; st=$?
[ $st -eq 1 ] || fail "error status $st"
[ "$(cat "$T/o")" = "before" ] || fail "stdout before error"
[ "$(sed -n 1p "$T/e")" = "lua: $T/err.lua:2: boom" ] || fail "error line: $(sed -n 1p "$T/e")"
[ "$(sed -n 2p "$T/e")" = "stack traceback:" ] || fail "traceback header"
grep -q "err.lua:3: in main chunk" "$T/e" || fail "traceback main chunk frame"
grep -q "err.lua:2: in" "$T/e" || fail "traceback function frame"

# syntax error
echo 'x = = 1' > "$T/syn.lua"
./lua "$T/syn.lua" > "$T/o" 2> "$T/e"; st=$?
[ $st -eq 1 ] || fail "syntax status"
[ "$(cat "$T/e")" = "lua: $T/syn.lua:1: unexpected symbol near '='" ] || fail "syntax msg: $(cat "$T/e")"

# error objects
echo 'error({})' > "$T/tbl.lua"; ./lua "$T/tbl.lua" 2> "$T/e"; [ $? -eq 1 ] || fail "tbl status"
[ "$(sed -n 1p "$T/e")" = "lua: (error object is a table value)" ] || fail "tbl msg"
echo 'error(setmetatable({}, {__tostring = function() return "custom!" end}))' > "$T/ts.lua"
./lua "$T/ts.lua" 2> "$T/e"; [ $? -eq 1 ] || fail "ts status"
[ "$(sed -n 1p "$T/e")" = "lua: custom!" ] || fail "ts msg: $(cat "$T/e")"
echo 'error("plain", 0)' > "$T/lv0.lua"; ./lua "$T/lv0.lua" 2> "$T/e"; [ "$(sed -n 1p "$T/e")" = "lua: plain" ] || fail "level 0 msg"
echo 'error()' > "$T/nil.lua"; ./lua "$T/nil.lua" 2> "$T/e"; [ $? -eq 1 ] || fail "nil error status"
[ "$(sed -n 1p "$T/e")" = "lua: (error object is a nil value)" ] || fail "nil msg: $(cat "$T/e")"

# runtime error with variable info
echo 'local t = nil; print(t.x)' > "$T/idx.lua"; ./lua "$T/idx.lua" 2> "$T/e"
[ "$(sed -n 1p "$T/e")" = "lua: $T/idx.lua:1: attempt to index a nil value (local 't')" ] || fail "idx msg: $(cat "$T/e")"

# missing script
./lua "$T/missing.lua" 2> "$T/e"; [ $? -eq 1 ] || fail "missing status"
grep -q "cannot open" "$T/e" || fail "missing message"

# script from stdin
out=$(echo 'print(1 + 1)' | ./lua -) || fail "stdin dash"; [ "$out" = "2" ] || fail "stdin out"
out=$(echo 'print("x")' | ./lua) || fail "stdin"; [ "$out" = "x" ] || fail "stdin implicit"

# shebang line
printf '#!/usr/bin/env lua\nprint("shebang ok")\n' > "$T/sb.lua"; [ "$(./lua "$T/sb.lua")" = "shebang ok" ] || fail "shebang"

# deep recursion does not crash the interpreter
echo 'local function f() return 1 + f() end; print(pcall(f)); print("alive")' > "$T/so.lua"
out=$(./lua "$T/so.lua") || fail "stack overflow crashed"; [ "$(echo "$out" | tail -1)" = "alive" ] || fail "alive after overflow"
echo ok
