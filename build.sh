#!/bin/bash
# Build GRTChronoImporter (one-folder) into dist/GRTChronoImporter on macOS or Linux.
# Needs Python 3.12+ with Tk (macOS: brew install python-tk@3.12). PYTHON picks the interpreter.
# For a Linux build from any machine with Docker, run build-linux.sh instead.
set -euo pipefail
cd "$(dirname "$0")"
py=${PYTHON:-python3}
[ -d .venv ] || "$py" -m venv .venv
.venv/bin/python -c 'import tkinter' || { echo "this Python has no Tk" >&2; exit 1; }
.venv/bin/python -m pip install -q -r requirements.txt
strip=(); [ "$(uname -s)" = Linux ] && strip=(--strip)   # debug symbols roughly double the Linux size
.venv/bin/pyinstaller --noconfirm --clean --onedir ${strip[@]+"${strip[@]}"} --name GRTChronoImporter --paths src src/plugin_main.py
cp GRTChronoImporter/com.grt.plugin.xml GRTChronoImporter/CHANGELOG.txt dist/GRTChronoImporter/
cp -R GRTChronoImporter/media dist/GRTChronoImporter/
echo "Built: dist/GRTChronoImporter"
