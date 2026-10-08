# GRT Chrono Importer

A plugin for [Gordon's Reloading Tool](https://www.grtools.de/doku.php?id=grtools:start) (GRT). It imports
chronograph data from the Garmin Xero C1 Pro or Athlon Rangecraft (CSV, XLS
or XLSX) into GRT as an Imported Measurement.

## Import modes

- **Standard:** one or more chrono files go into an Imported Measurement tab.
  The charge weight comes from a base `.grtload`.
- **Ladder:** one chrono file per charge in the ladder. The top charge and
  step sizes come from the base ladder `.grtload`. Ladders whose steps
  aren't all the same size are supported.
- **Sessions:** one workbook where each worksheet is a shooting session.
  Each session becomes its own charge in an Imported Sessions tab, named by
  the session date. Use this to compare velocity strings that aren't a
  charge ladder.
- **Chrono vs Sim:** in Ladder mode, add a GRT "Export simulation results"
  JSON. The plugin then adds an Analysis tab and a chart comparing measured
  and simulated velocity for each charge.

The plugin saves the result as a new `.grtload`, then offers to open it in
GRT. Suggested file names keep the base file's name as written and append the
date and time, e.g. `... 10 Step Ladder (Raw) 2026-10-08 0716.grtload`.

## Install

1. Download the zip from [Releases](../../releases).
2. Close GRT.
3. Open `%USERPROFILE%\GordonsReloadingTool\plugins\` and delete any old
   `GRTChronoImporter` folder.
4. Copy the `GRTChronoImporter` folder from the zip into that plugins folder.
5. Start GRT. The importer's window title shows the installed version.

Start the plugin from GRT's toolbar or menu. Running the exe by itself only
shows a message telling you to launch it from inside GRT.

## Source and build

The source was reconstructed from the 1.0.0 executable. See
[BUILD.md](BUILD.md) for the file layout and the Windows build steps, and
[CHANGELOG.txt](GRTChronoImporter/CHANGELOG.txt) for release history.
