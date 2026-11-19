#!/bin/sh
# Test runner: builds the interpreter, runs tests/cases/*.lua (self-checking; optional .expected stdout),
# the CLI tests and the benchmark tests. Exit status is non-zero if anything fails.
cd "$(dirname "$0")/.." || exit 1
make -s || exit 1
pass=0; fail=0
ok()   { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }

for f in tests/cases/*.lua; do
  exp="${f%.lua}.expected"
  out=$(./lua "$f" 2>/tmp/lua_test_err.$$); st=$?
  if [ $st -ne 0 ]; then bad "$f (exit $st)"; cat /tmp/lua_test_err.$$ | head -20; continue; fi
  if [ -f "$exp" ]; then
    if [ "$out" = "$(cat "$exp")" ]; then ok "$f"; else bad "$f (stdout differs from $exp)"; fi
  else ok "$f"; fi
done
rm -f /tmp/lua_test_err.$$

for f in tests/cli/*.sh; do
  if sh "$f" >/tmp/lua_cli_out.$$ 2>&1; then ok "$f"; else bad "$f"; cat /tmp/lua_cli_out.$$ | head -30; fi
done
rm -f /tmp/lua_cli_out.$$

for f in tests/bench/*.lua; do
  limit=$(sed -n 's/^-- limit: *\([0-9][0-9]*\).*/\1/p' "$f" | head -1); [ -n "$limit" ] || limit=10
  s=$(date +%s%N)
  if timeout 120 ./lua "$f" >/dev/null 2>/tmp/lua_bench_err.$$; then
    e=$(date +%s%N); ms=$(( (e - s) / 1000000 ))
    if [ $ms -le $((limit * 1000)) ]; then ok "$f (${ms}ms <= ${limit}s)"; else bad "$f (${ms}ms > ${limit}s)"; fi
  else bad "$f (failed)"; head -5 /tmp/lua_bench_err.$$; fi
done
rm -f /tmp/lua_bench_err.$$

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ $fail -eq 0 ]
