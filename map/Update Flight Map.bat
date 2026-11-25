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

rem ---- Publish the data to GitHub Pages ----
where git >nul 2>&1
if errorlevel 1 goto nogit
pushd "%~dp0.."
git -c core.safecrlf=false add -- map/flights-data.js
if errorlevel 1 goto pubfail
git diff --cached --quiet -- map/flights-data.js
if not errorlevel 1 goto nochange
git commit -m "Update flight data" -- map/flights-data.js
if errorlevel 1 goto pubfail
git push
if errorlevel 1 goto pubfail
echo.
echo Online map updated: https://wyler6.github.io/FlightRecorder/ (GitHub takes about a minute)
goto pubdone

:nogit
echo.
echo Git was not found, so publishing to the online map was skipped.
goto done

:nochange
echo.
echo No new flights to publish.
goto pubdone

:pubfail
echo.
echo Publishing to GitHub failed. See the messages above.
echo The local map has been updated.
pause

:pubdone
popd

:done
start "" "%~dp0flight_map.html"
