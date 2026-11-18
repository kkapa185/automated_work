#!/bin/sh
# Smoke test: UCI handshake, a search and a perft through the real binary; fails if output is wrong.
cd "$(dirname "$0")" || exit 1
out=$(printf 'uci\nisready\nposition startpos\ngo depth 4\ngo perft 3\nquit\n' | ./engine) || exit 1
echo "$out" | grep -q '^uciok' || exit 1
echo "$out" | grep -q '^readyok' || exit 1
echo "$out" | grep -q '^bestmove ' || exit 1
echo "$out" | grep -q '^Nodes searched: 8902$' || exit 1
echo "$out" | tail -3
