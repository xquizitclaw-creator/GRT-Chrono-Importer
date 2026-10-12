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
date and time, e.g. `... 10 Step Ladder (Raw) 2026-10-08 071624.grtload`.
The stamp carries seconds so every import is a new file: GRT answers a request
to open a path it already has open with that tab's existing results, so reusing
a name would show you the previous import's numbers.

## Install

You need GRT installed first. grtools.de no longer offers the download.
Get GRT from the [download channel](https://discordapp.com/channels/621039234404581406/1201641174889414841)
on the GRT Discord. If the link doesn't open, join the server first with
the [invite](https://discord.gg/3FEYWG4).

1. Download the zip from [Releases](../../releases).
2. Close GRT.
3. Open `%USERPROFILE%\GordonsReloadingTool\plugins\` and delete any old
   `GRTChronoImporter` folder.
4. Copy the `GRTChronoImporter` folder from the zip into that plugins folder.
5. Start GRT. The importer's window title shows the installed version.

Start the plugin from GRT's toolbar or menu. Running the exe by itself only
shows a message telling you to launch it from inside GRT.

## Related: the GRT Reloading Toolkit

FREESHOTER's [GRT Reloading Toolkit](https://github.com/FREESHOTER/GRT-Reloading-Toolkit)
is a suite of reloading tools in one GRT plugin, and it has a chronograph importer of its
own that reads the same Garmin and Athlon files. The two overlap, so which one you want
depends on what you are doing:

- **This plugin** handles **ladders whose steps aren't all the same size**, and it charts
  measured velocity against GRT's *exported* simulation results (an "Export simulation
  results" JSON), so you can compare a ladder you shot weeks ago against a simulation
  without having the load open. **Sessions mode** turns a multi-worksheet Garmin workbook
  into one charge per session, for strings that aren't a charge ladder at all.
- **The Toolkit** compares measured against simulated velocity **live through GRT** in its
  Barrel Calibration tool, rather than from a JSON file, and it does far more besides the
  import: brass prep, seating depth, ladder/OCW analysis, group analysis, powder
  temperature coefficients, a load journal and more. If you want one plugin for the whole
  workflow, start there.

Using both is fine; they write ordinary `.grtload` files and don't interfere.

## Licence

[MIT](LICENSE). Use it, fork it, fold it into something else.

## Source and build

The source was reconstructed from the 1.0.0 executable. See
[BUILD.md](BUILD.md) for the file layout and the Windows build steps, and
[CHANGELOG.txt](GRTChronoImporter/CHANGELOG.txt) for release history.
