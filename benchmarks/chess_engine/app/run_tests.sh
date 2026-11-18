#!/bin/sh
# Build the engine and run the whole test suite (stdlib unittest only).
cd "$(dirname "$0")" || exit 1
make -s build/engine >&2 || exit 1
exec python3 -W ignore -m unittest discover -s tests
