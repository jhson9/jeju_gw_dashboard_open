@echo off
REM ==========================================================================
REM  Run_JejuDashboard.bat (2026-05-29 v3 ASCII-only)
REM
REM  CRITICAL: This file MUST stay ASCII-only.
REM  Korean comments/echo cause cmd to garble on CP949 systems even after
REM  chcp 65001 (chcp is applied AFTER the file is parsed line-by-line).
REM  All Korean user messages are delegated to launch_dashboard.py (UTF-8).
REM
REM  Behavior:
REM    1. Set UTF-8 codepage (best effort)
REM    2. Detect a Python launcher (py -> python -> python3)
REM    3. Delegate everything to launch_dashboard.py
REM    4. Always pause on exit so the console window stays open
REM ==========================================================================
chcp 65001 >nul 2>nul
title Jeju Groundwater Dashboard Launcher
cd /d "%~dp0"

echo ============================================================
echo  Jeju Groundwater Dashboard - Launcher v3
echo ============================================================
echo.

REM ---- Detect Python with smoke test ----
REM 2026-05-29 fix: Windows App Execution Aliases stub detection.
REM where command matches 0-byte stubs that silently open Store page.
REM Each candidate must pass BOTH `where` AND `-c "import sys"` smoke test.
set PY_CMD=
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set PY_CMD=py -3
        goto :py_found
    )
)
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set PY_CMD=python
        goto :py_found
    )
)
where python3 >nul 2>nul
if not errorlevel 1 (
    python3 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set PY_CMD=python3
        goto :py_found
    )
)

echo [!] ERROR: Python not found or non-functional on PATH.
echo     Possible causes:
echo       1. Python not installed - get it from https://python.org
echo          (check "Add to PATH" during install)
echo       2. Microsoft Store stub launcher detected - install actual Python
echo          or disable App Execution Aliases:
echo          Settings ^> Apps ^> Advanced app settings ^> App execution aliases
echo          ^> turn OFF python.exe and python3.exe
echo.
pause
exit /b 1

:py_found
echo  Python launcher: %PY_CMD%
echo.

REM ---- Delegate to Python launcher (handles port discovery, browser, errors) ----
%PY_CMD% "%~dp0desktop_app.py" %*
set RC=%errorlevel%

if not "%RC%"=="0" (
    echo.
    echo [!] launch_dashboard.py exited with errorlevel=%RC%
    echo     See messages above. Scroll up to read details.
)

echo.
echo --------------------------------------------------------
pause
exit /b %RC%
