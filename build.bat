@echo off
rem Build GRTChronoImporter.exe (one-folder) into dist\GRTChronoImporter
rem Needs Python 3.14 on PATH (py launcher).
setlocal
cd /d "%~dp0"
if not exist .venv py -3.14 -m venv .venv || exit /b 1
.venv\Scripts\python -m pip install -q -r requirements.txt || exit /b 1
.venv\Scripts\pyinstaller --noconfirm --clean --windowed --onedir ^
  --name GRTChronoImporter --paths src src\plugin_main.py || exit /b 1
copy /y GRTChronoImporter\com.grt.plugin.xml dist\GRTChronoImporter\ >nul
copy /y GRTChronoImporter\CHANGELOG.txt dist\GRTChronoImporter\ >nul
xcopy /e /i /y GRTChronoImporter\media dist\GRTChronoImporter\media >nul
echo.
echo Built: dist\GRTChronoImporter
echo Install: close GRT, replace the contents of
echo   %%USERPROFILE%%\GordonsReloadingTool\plugins\GRTChronoImporter
echo with that folder, then restart GRT.
