@echo off
cd /d "%~dp0"

set "QGIS_ROOT="
set "QGIS_PYTHON_BAT="

for /d %%D in ("%ProgramFiles%\QGIS*") do (
    if exist "%%~fD\bin\python-qgis.bat" (
        set "QGIS_ROOT=%%~fD"
        set "QGIS_PYTHON_BAT=%%~fD\bin\python-qgis.bat"
        goto :found
    )
    if exist "%%~fD\bin\python-qgis-ltr.bat" (
        set "QGIS_ROOT=%%~fD"
        set "QGIS_PYTHON_BAT=%%~fD\bin\python-qgis-ltr.bat"
        goto :found
    )
)

:found
if not defined QGIS_ROOT (
    echo QGIS is not found.
    pause
    exit /b 1
)

echo found QGIS: %QGIS_ROOT%
echo starting %QGIS_PYTHON_BAT%
call "%QGIS_PYTHON_BAT%" "%~dp0cart.py"
pause