#!/bin/bash
# Starts the real server via ./serve, runs a few commands with redis-cli if present
# (otherwise a raw TCP exchange via bash), then stops it.
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
dir=$(mktemp -d)
port=$((20000 + $$ % 20000))
"$root/serve" --port "$port" --dir "$dir" >/dev/null 2>&1 &
pid=$!
trap 'kill $pid 2>/dev/null; rm -rf "$dir"' EXIT
i=0
until (exec 3<>/dev/tcp/127.0.0.1/$port) 2>/dev/null; do
  i=$((i+1)); [ $i -gt 100 ] && { echo "server did not start"; exit 1; }; sleep 0.1
done
exec 3<>/dev/tcp/127.0.0.1/$port
printf 'SET k v\r\nGET k\r\nPING\r\n' >&3
sleep 0.3
timeout 1 cat <&3 > "$dir/out" || true
grep -q '^+OK' "$dir/out" && grep -q '^v' "$dir/out" && grep -q '^+PONG' "$dir/out"
echo smoke ok
