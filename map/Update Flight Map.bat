@echo off
setlocal
set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
set "EXPORTER=%~dp0..\tools\flightmap_export.py"
where py >nul 2>&1
if not errorlevel 1 (
    py -3 "%EXPORTER%"
) else (
    "%PYEXE%" "%EXPORTER%"
)
if errorlevel 1 (
    echo.
    echo The export failed. See the messages above.
    pause
    exit /b 1
)
start "" "%~dp0flight_map.html"
