#!/bin/sh
# Smoke run: pipes the sample through jsondump and checks the result.
set -e
build/jsondump < example/sample.json | diff - example/sample.expected
build/simple | grep -q 'User: johndoe'
