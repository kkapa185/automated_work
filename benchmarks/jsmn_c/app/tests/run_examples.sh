#!/bin/sh
# Smoke tests for the examples (R19). Usage: run_examples.sh <build-dir>
set -e
B=${1:-build}
fail() { echo "examples FAIL: $1"; exit 1; }

"$B/simple" > "$B/simple.out" || fail "simple exit"
grep -qx -- '- User: johndoe' "$B/simple.out" || fail "simple user"
grep -qx -- '- Admin: false' "$B/simple.out" || fail "simple admin"
grep -qx -- '- UID: 1000' "$B/simple.out" || fail "simple uid"
grep -qx -- '  \* audio' "$B/simple.out" || fail "simple groups"

printf '{"a":[1,2,{"b":null}],"c":"x\\ny","d":{},"e":[]}' | "$B/jsondump" > "$B/dump.out" || fail "dump exit"
cat > "$B/dump.exp" <<'EOT'
{
  "a": [
    1,
    2,
    {
      "b": null
    }
  ],
  "c": "x\ny",
  "d": {},
  "e": []
}
EOT
cmp "$B/dump.out" "$B/dump.exp" || fail "dump output"

# large input forces several token-array growths
i=0; { printf '['; while [ $i -lt 2000 ]; do printf '%s{"k":%s},' "" $i; i=$((i+1)); done; printf '0]'; } > "$B/big.json"
"$B/jsondump" < "$B/big.json" > "$B/big.out" || fail "big exit"
[ "$(grep -c '"k"' "$B/big.out")" -eq 2000 ] || fail "big count"

if printf '[1,2' | "$B/jsondump" >/dev/null 2>&1; then fail "partial should fail"; fi
if printf ']' | "$B/jsondump" >/dev/null 2>&1; then fail "invalid should fail"; fi
echo "examples ok"
