# GRT Chrono Importer: source and build

`src/` holds the plugin source. The original source was lost, so it was
reconstructed from the 1.0.0 executable and checked against its compiled
bytecode; every code object matched. That unchanged 1.0.0 reconstruction is
kept in `src_original/` for diffing.

| File | Role |
|---|---|
| `src/plugin_main.py` | Entry point and Tkinter UI (`GRTChronoImporter.exe --ipcport <port>`) |
| `src/chrono_import.py` | Chrono file parsing and .grtload building (standard/ladder/sessions) |
| `src/sim_compare.py` | Chrono vs Sim matching, Analysis note, and chart (Pillow) |
| `src/grt_ipc.py` | TCP JSON link back to GRT |

## Build (Windows)

1. Install Python 3.14 (python.org, with the `py` launcher).
2. Run `build.bat`. It creates `.venv`, installs `requirements.txt`
   (pillow, xlrd, pyinstaller), and builds into `dist\GRTChronoImporter`.
   It also copies in the manifest, changelog, and icons.
3. Close GRT. Replace `%USERPROFILE%\GordonsReloadingTool\plugins\GRTChronoImporter`
   with `dist\GRTChronoImporter`, then start GRT.

## Build (macOS and Linux)

The same source builds on macOS and Linux; the manifest has `launch-macos`
and `launch-linux` entries for those builds.

- **macOS (Apple silicon):** `brew install python-tk@3.12`, then
  `PYTHON=/opt/homebrew/bin/python3.12 ./build.sh`. Output:
  `dist/GRTChronoImporter` (arm64, ad-hoc signed by PyInstaller). An Intel
  build needs an x86_64 Python with Tk, such as the python.org universal2
  installer.
- **Linux x64:** `./build-linux.sh` (needs Docker). It builds in Debian
  bullseye (glibc 2.31), so it runs on Ubuntu 20.04 and newer. Output:
  `dist/linux-x64/GRTChronoImporter`. Tested headless on Ubuntu 24.04 and
  Fedora under Xvfb: it starts and connects to the host.

GRTMultiPlatform bundles these from its `bundled-plugins/<rid>` folder.

The plugin only runs when GRT launches it. Starting the exe directly shows a
"launch it from inside GRT" message.
