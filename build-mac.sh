#!/bin/bash
# Build the macOS plugin into dist/osx-arm64/GRTChronoImporter (default) or, with x86_64,
# dist/osx-x64/GRTChronoImporter. Uses uv's portable Python (python-build-standalone, with Tk),
# which targets macOS 11 (arm64) / 10.13 (x86_64); Homebrew's Python only runs on the build
# machine's own macOS version or newer.
#   uv python install cpython-3.12-macos-aarch64-none     # arm64
#   uv python install cpython-3.12-macos-x86_64-none      # x86_64 (needs Rosetta on Apple silicon)
# PYTHON=<python3.12 of that arch> overrides the uv one. Builds in a temp copy so each arch has its own venv.
set -euo pipefail
cd "$(dirname "$0")"
arch=${1:-arm64}
case $arch in
  arm64) uvname=cpython-3.12-macos-aarch64-none out=dist/osx-arm64 run=() ;;
  x86_64) uvname=cpython-3.12-macos-x86_64-none out=dist/osx-x64 run=(arch -x86_64) ;;
  *) echo "usage: $0 [arm64|x86_64]" >&2; exit 2 ;;
esac
py=${PYTHON:-$(uv python find "$uvname")}
file "$py" | grep -q "$arch" || { echo "not an $arch Python: $py" >&2; exit 1; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
rm -rf "$out" && mkdir -p "$out"
tar -cf - --exclude ./.venv --exclude ./dist --exclude ./build --exclude ./.worktrees --exclude '*.zip' . | tar xf - -C "$tmp"
(cd "$tmp" && PYTHON="$py" ${run[@]+"${run[@]}"} ./build.sh)
cp -R "$tmp/dist/GRTChronoImporter" "$out/"
echo "Built: $out/GRTChronoImporter"
