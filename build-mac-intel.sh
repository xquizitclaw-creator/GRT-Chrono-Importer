#!/bin/bash
# Build the Intel Mac (x86_64) plugin into dist/osx-x64/GRTChronoImporter, on an Apple silicon Mac.
# Needs Rosetta and an x86_64 Python with Tk:  uv python install cpython-3.12-macos-x86_64-none
# PYTHON=<x86_64 python3.12> overrides the uv one. Builds in a temp copy so its venv stays apart from the arm64 one.
set -euo pipefail
cd "$(dirname "$0")"
py=${PYTHON:-$(uv python find cpython-3.12-macos-x86_64-none)}
file "$py" | grep -q x86_64 || { echo "not an x86_64 Python: $py" >&2; exit 1; }
out=dist/osx-x64 tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
rm -rf "$out" && mkdir -p "$out"
tar -cf - --exclude ./.venv --exclude ./dist --exclude ./build --exclude ./.worktrees --exclude '*.zip' . | tar xf - -C "$tmp"
(cd "$tmp" && PYTHON="$py" arch -x86_64 ./build.sh)
cp -R "$tmp/dist/GRTChronoImporter" "$out/"
echo "Built: $out/GRTChronoImporter"
