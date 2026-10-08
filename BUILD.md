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

The plugin only runs when GRT launches it. Starting the exe directly shows a
"launch it from inside GRT" message.
