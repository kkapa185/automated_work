#!/bin/sh
cd "$(dirname "$0")/../.." || exit 1
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail() { echo "CLI FAIL: $1"; exit 1; }
echo 'return {v = 42, args = {...}}' > "$T/mod.lua"
echo "local m = dofile('$T/mod.lua'); print(m.v); local f = assert(loadfile('$T/mod.lua')); print(f('x').args[1]); print(loadfile('$T/none.lua'))" > "$T/main.lua"
out=$(./lua "$T/main.lua") || fail "run"
[ "$(echo "$out" | sed -n 1p)" = "42" ] || fail "dofile"; [ "$(echo "$out" | sed -n 2p)" = "x" ] || fail "loadfile args"
echo "$out" | sed -n 3p | grep -q "^nil	cannot open" || fail "loadfile missing"
echo ok
