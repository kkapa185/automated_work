#!/bin/sh
# R19/R20: os.exit status codes, stdin/stdout/stderr behaviour
cd "$(dirname "$0")/../.." || exit 1
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail() { echo "CLI FAIL: $1"; exit 1; }
./lua -e 'io.write("pending"); os.exit(3)' > "$T/o"; [ $? -eq 3 ] || fail "os.exit(3) status"
[ "$(cat "$T/o")" = "pending" ] || fail "stdout flushed on os.exit"
./lua -e 'os.exit(true)'; [ $? -eq 0 ] || fail "os.exit(true)"
./lua -e 'os.exit(false)'; [ $? -eq 1 ] || fail "os.exit(false)"
./lua -e 'os.exit()'; [ $? -eq 0 ] || fail "os.exit()"
out=$(printf 'first line\n42 3.5\nrest\nof file\n' | ./lua -e 'print(io.read()); print(io.read("n", "n")); print(io.read("L")); print(io.read("a")); print(io.read())') || fail "stdin read"
[ "$out" = "first line
42	3.5


rest
of file

nil" ] || fail "stdin read output: $out"
out=$(printf 'a\nb\nc\n' | ./lua -e 'for l in io.lines() do io.write("[", l, "]") end print()') || fail "io.lines stdin"
[ "$out" = "[a][b][c]" ] || fail "io.lines output: $out"
out=$(printf 'x\ny\n' | ./lua -e 'for l in io.stdin:lines() do io.write(l, ";") end print()') || fail "stdin:lines"
[ "$out" = "x;y;" ] || fail "stdin:lines output"
./lua -e 'io.stderr:write("to stderr\n"); io.stdout:write("to stdout\n")' > "$T/o" 2> "$T/e"
[ "$(cat "$T/o")" = "to stdout" ] || fail "stdout content"; [ "$(cat "$T/e")" = "to stderr" ] || fail "stderr content"
printf 'print("script", ...)\nprint(arg[0])' > "$T/s.lua"; out=$(./lua "$T/s.lua" x y) ; [ "$(echo "$out" | head -1)" = "script	x	y" ] || fail "script args"
out=$(./lua -e 'print(#arg, arg[0])' ) ; [ "$out" = "0	nil" ] || fail "-e arg: $out"
echo ok
