#!/bin/sh
# Runs every tests/cases/*.lua through ./lua and compares stdout with the
# matching .expected file, then runs the CLI tests. Exit status 0 iff all pass.
cd "$(dirname "$0")/.." || exit 1
LUA=./lua
fail=0
pass=0
for f in tests/cases/*.lua; do
  exp="${f%.lua}.expected"
  [ -f "$exp" ] || continue
  out=$($LUA "$f" 2>&1)
  if [ "$out" = "$(cat "$exp")" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    echo "FAIL: $f"
    echo "$out" | head -20
  fi
done

check() { # name expected actual
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: $1"; echo "  expected: $2"; echo "  actual:   $3"; fi
}

# --- CLI: arg table and varargs (R1)
out=$($LUA tests/cases/args_script.lua a b)
check "cli args" "2	tests/cases/args_script.lua	a	b	a	b
2" "$out"
out=$($LUA tests/cases/args_script.lua)
check "cli no args" "0	tests/cases/args_script.lua	nil	nil
0" "$out"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# --- uncaught runtime error: message + traceback on stderr, exit 1 (R2)
printf 'local function f()\n  error("boom")\nend\nf()\n' > "$TMP/err.lua"
$LUA "$TMP/err.lua" > "$TMP/o" 2> "$TMP/e"; code=$?
check "error exit status" "1" "$code"
check "error stdout empty" "" "$(cat "$TMP/o")"
check "error first line" "lua: $TMP/err.lua:2: boom" "$(head -n 1 "$TMP/e")"
check "error traceback header" "stack traceback:" "$(sed -n 2p "$TMP/e")"
grep -q "err.lua:4: in main chunk" "$TMP/e"; check "traceback has main chunk" "0" "$?"
grep -q "err.lua:2: in" "$TMP/e"; check "traceback has function frame" "0" "$?"

# --- output before the error is still flushed, in order
printf 'print("before")\nlocal t = nil\nprint(t.x)\n' > "$TMP/e2.lua"
$LUA "$TMP/e2.lua" > "$TMP/o" 2> "$TMP/e"; code=$?
check "partial stdout" "before" "$(cat "$TMP/o")"
check "runtime error msg" "lua: $TMP/e2.lua:3: attempt to index a nil value (local 't')" "$(head -n 1 "$TMP/e")"
check "runtime error status" "1" "$code"

# --- syntax error
printf 'x = = 1\n' > "$TMP/syn.lua"
$LUA "$TMP/syn.lua" > "$TMP/o" 2> "$TMP/e"; code=$?
check "syntax error status" "1" "$code"
check "syntax error msg" "lua: $TMP/syn.lua:1: unexpected symbol near '='" "$(head -n 1 "$TMP/e")"

# --- error with non-string value
printf 'error({})\n' > "$TMP/tbl.lua"
$LUA "$TMP/tbl.lua" 2> "$TMP/e"; code=$?
check "table error status" "1" "$code"
check "table error msg" "lua: (error object is a table value)" "$(head -n 1 "$TMP/e")"
printf 'error(setmetatable({}, {__tostring = function() return "custom!" end}))\n' > "$TMP/ts.lua"
$LUA "$TMP/ts.lua" 2> "$TMP/e"
check "__tostring error object" "lua: custom!" "$(head -n 1 "$TMP/e")"

# --- missing script
$LUA "$TMP/nonexistent.lua" > /dev/null 2> "$TMP/e"; code=$?
check "missing script status" "1" "$code"

# --- script from stdin, shebang line
printf 'print("from stdin")\n' | $LUA > "$TMP/o"
check "stdin script" "from stdin" "$(cat "$TMP/o")"
printf '#!/usr/bin/env lua\nprint("shebang", 1+1)\nerror("line3")\n' > "$TMP/sb.lua"
$LUA "$TMP/sb.lua" > "$TMP/o" 2> "$TMP/e"
check "shebang stdout" "shebang	2" "$(cat "$TMP/o")"
check "shebang line numbers" "lua: $TMP/sb.lua:3: line3" "$(head -n 1 "$TMP/e")"

# --- require of a module next to the script
mkdir -p "$TMP/sub"
printf 'return {v = 42}\n' > "$TMP/sub/helper.lua"
printf 'print(require("helper").v)\n' > "$TMP/sub/main.lua"
check "require relative to script dir" "42" "$($LUA "$TMP/sub/main.lua")"

# --- deep recursion is a catchable error, not a crash
printf 'local function f() return 1 + f() end\nlocal ok, e = pcall(f)\nprint(ok, e:match("stack overflow") ~= nil)\n' > "$TMP/so.lua"
printf 'local function f() return 1 + f() end\nprint(pcall(f))\n' > "$TMP/so.lua"
$LUA "$TMP/so.lua" > "$TMP/o" 2>&1; code=$?
check "stack overflow exit" "0" "$code"
grep -q "false	.*stack overflow" "$TMP/o"; check "stack overflow message" "0" "$?"

# --- os.exit codes (R18)
$LUA -e "os.exit(3)"; check "os.exit(3)" "3" "$?"
$LUA -e "os.exit(true)"; check "os.exit(true)" "0" "$?"
$LUA -e "os.exit(false)"; check "os.exit(false)" "1" "$?"
out=$($LUA -e "io.write('buffered'); os.exit(0)"); check "os.exit flushes stdout" "buffered" "$out"

# --- io.read from stdin (R18)
printf 'first line\n42 3.5 0x10\nrest of\ndata' > "$TMP/in.txt"
cat > "$TMP/rd.lua" <<'LUA'
print(io.read())
print(io.read("n", "n", "n"))
print(io.read("L"))
print(io.read(4))
print(io.read("a"))
print(io.read("a"))
print(io.read("l"))
LUA
out=$($LUA "$TMP/rd.lua" < "$TMP/in.txt")
check "stdin read formats" "first line
42	3.5	16


rest
 of
data

nil" "$out"
# the "L" read returns the remainder of the numbers line, i.e. "\n"
printf 'a\nb\nc\n' | $LUA -e "for l in io.lines() do io.write('[', l, ']') end print()" > "$TMP/o"
check "io.lines on stdin" "[a][b][c]" "$(cat "$TMP/o")"
printf 'x y\n' | $LUA -e "local a, b = io.read('n', 'l'); print(a, b)" > "$TMP/o"
check "read n on non-number" "nil	nil" "$(cat "$TMP/o")"

# --- stderr is separate from stdout and ordered after flushed stdout
$LUA -e "io.write('out1 '); io.stderr:write('err1\n'); io.write('out2\n')" > "$TMP/o" 2> "$TMP/e"
check "stdout content" "out1 out2" "$(cat "$TMP/o")"
check "stderr content" "err1" "$(cat "$TMP/e")"

# --- performance smoke tests (R20): generous wall-clock limits in ms
perf() { # name file limit_ms
  t0=$(date +%s%N)
  $LUA "$2" > "$TMP/o" 2>&1; code=$?
  t1=$(date +%s%N)
  ms=$(( (t1 - t0) / 1000000 ))
  if [ "$code" -eq 0 ] && [ "$ms" -lt "$3" ]; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: perf $1 (exit $code, ${ms}ms, limit $3ms)"; cat "$TMP/o"; fi
}
perf "fib(25)" tests/perf/fib.lua 2000
perf "1e6 loop" tests/perf/loop.lua 1000
perf "tables/strings" tests/perf/tables.lua 3000

echo "passed: $pass failed: $fail"
[ "$fail" -eq 0 ]
