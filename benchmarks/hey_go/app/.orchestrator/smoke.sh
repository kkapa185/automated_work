#!/bin/sh
set -e
go build -o hey .
python3 -m http.server 18765 --bind 127.0.0.1 >/dev/null 2>&1 &
P=$!
trap 'kill $P' EXIT
sleep 1
./hey -n 20 -c 4 http://127.0.0.1:18765/
./hey -n 3 -c 1 -o csv http://127.0.0.1:18765/
