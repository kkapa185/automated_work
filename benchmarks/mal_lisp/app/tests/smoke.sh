#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
out=$(printf '(let* (a 6) (+ a 8))\n' | STEP=step3_env ./run) || exit 1
echo "$out"
echo "$out" | grep -q '^user> 14$'
