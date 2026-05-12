#!/bin/bash
set -e

mkdir -p build
cmake -H. -Bbuild -DCMAKE_BUILD_TYPE=Release
cmake --build build -- -j"$(nproc)"

[[ -f hailort.log ]] && rm hailort.log
