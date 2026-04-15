#!/bin/bash
set -e

echo "-I- Building low_power_poc"
mkdir -p build
cmake -H. -Bbuild
cmake --build build
echo "-I- Build complete: build/low_power_poc"

if [[ -f "hailort.log" ]]; then
    rm hailort.log
fi
