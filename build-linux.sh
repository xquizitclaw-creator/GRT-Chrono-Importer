#!/bin/bash
# Build the linux-x64 plugin in Docker into dist/linux-x64/GRTChronoImporter.
# Debian bullseye (glibc 2.31) so it runs on Ubuntu 20.04 and newer.
set -euo pipefail
cd "$(dirname "$0")"
out=dist/linux-x64
rm -rf "$out" && mkdir -p "$out"
tar -cf - --exclude ./.venv --exclude ./dist --exclude ./build --exclude ./.worktrees --exclude '*.zip' . |
  docker run --rm -i --platform linux/amd64 python:3.12-bullseye bash -c \
    'mkdir /b && cd /b && tar xf - && ./build.sh >&2 && tar cf - -C dist GRTChronoImporter' |
  tar xf - -C "$out"
echo "Built: $out/GRTChronoImporter"
