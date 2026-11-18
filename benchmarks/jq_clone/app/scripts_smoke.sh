#!/bin/sh
cd "$(dirname "$0")" || exit 1
out=$(echo '{"a":[1,2,3]}' | ./jq -c '.a | map(. * 2) | add') || exit 1
[ "$out" = "12" ]
