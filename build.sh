#!/bin/bash
# Build GRTChronoImporter (one-folder) into dist/GRTChronoImporter on macOS or Linux.
# Needs Python 3.12+ with Tk. PYTHON picks the interpreter. For the macOS builds that ship,
# run build-mac.sh (portable Python, runs on macOS 11+); for Linux, build-linux.sh (Docker).
set -euo pipefail
cd "$(dirname "$0")"
py=${PYTHON:-python3}
base() { "$1" -c 'import sys; print(sys.base_prefix)'; }
# A .venv from another interpreter would silently ignore PYTHON: start it again
[ -x .venv/bin/python ] && [ "$(base .venv/bin/python)" = "$(base "$py")" ] || { rm -rf .venv; "$py" -m venv .venv; }
.venv/bin/python -c 'import tkinter' || { echo "this Python has no Tk: $py" >&2; exit 1; }
.venv/bin/python -m pip install -q -r requirements.txt
strip=(); [ "$(uname -s)" = Linux ] && strip=(--strip)   # debug symbols roughly double the Linux size
.venv/bin/pyinstaller --noconfirm --clean --onedir ${strip[@]+"${strip[@]}"} --name GRTChronoImporter --paths src src/plugin_main.py
cp GRTChronoImporter/com.grt.plugin.xml GRTChronoImporter/CHANGELOG.txt dist/GRTChronoImporter/
cp -R GRTChronoImporter/media dist/GRTChronoImporter/
echo "Built: dist/GRTChronoImporter"
