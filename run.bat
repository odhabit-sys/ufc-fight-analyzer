@echo off
rem Start the Fight Analyzer on Windows. Double-click this file, or run it from a terminal.
rem The first run sets everything up (Python environment, dependencies, model weights).
rem Python 3.13 is preferred; 3.12 and 3.14 also work. A newer Python found as "py -3" or
rem "python" is passed on, and launch.py then explains that it is too new.
setlocal
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if defined PY goto start
rem First run: find Python. With the Python install manager and no Python yet, "py -3.13"
rem downloads Python 3.13 by itself, which takes a minute with no output.
echo Looking for Python 3.13 (3.12 and 3.14 also work); this can take a minute ...
py -3.13 -c "import sys" >nul 2>&1 && set "PY=py -3.13"
if defined PY goto start
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if defined PY goto start
py -3.14 -c "import sys" >nul 2>&1 && set "PY=py -3.14"
if defined PY goto start
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1 && set "PY=py -3"
if defined PY goto start
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1 && set "PY=python"
if defined PY goto start
goto nopython

:start
%PY% launch.py %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" pause
exit /b %CODE%

:nopython
echo.
echo ==========================================================================
echo   ERROR: Python 3.12 or newer was not found.
echo.
echo   Install Python 3.13 [64-bit] from https://www.python.org/downloads/windows/
echo   and tick "Add python.exe to PATH" on the first installer screen.
echo   Then double-click run.bat again.
echo ==========================================================================
echo.
pause
exit /b 1
