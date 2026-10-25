@echo off
REM LitUbik launcher - double-click to run.
REM Builds the frontend if needed, migrates the DB, starts the server on port 8000
REM and opens your browser. Close this window (or Ctrl+C) to stop the app.
REM
REM Prerequisites:
REM   - Python 3.12+ on PATH (install from python.org, tick "Add python.exe to PATH").
REM   - Node.js is optional: if npm is missing, this script downloads a local copy
REM     (no admin rights) into %LOCALAPPDATA%\litubik\node.
setlocal
cd /d "%~dp0"
set "PATH=%ProgramFiles%\nodejs;%PATH%"
set "NODE_DIR=%LOCALAPPDATA%\litubik\node"

REM -- Python venv --------------------------------------------------------------
if exist backend\.venv\Scripts\python.exe goto :frontend
call :find_python
if not defined PY_CMD goto :python_fail
echo [LitUbik] Creating Python environment with: %PY_CMD%
%PY_CMD% -m venv backend\.venv
if errorlevel 1 goto :python_fail
REM a fresh venv can ship a pip too old to use wheels for some packages, which
REM then tries to build them from source and fails on a machine without a compiler
backend\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto :fail

:frontend
REM -- Frontend build (skipped with: start.bat --no-build) -----------------------
if "%~1"=="--no-build" goto :migrate
where npm >nul 2>nul
if not errorlevel 1 goto :npm_ready
if exist "%NODE_DIR%\npm.cmd" (
    set "PATH=%NODE_DIR%;%PATH%"
    echo [LitUbik] Using local Node.js at %NODE_DIR%
    goto :npm_ready
)
call :bootstrap_node
if errorlevel 1 goto :node_fail
set "PATH=%NODE_DIR%;%PATH%"

:npm_ready
REM Reinstall when node_modules is missing OR package.json changed since last install.
call :need_install
if not defined NEED_INSTALL goto :build
echo [LitUbik] Installing frontend dependencies...
cd frontend
call npm install
if errorlevel 1 goto :fail
cd ..
call :save_pkg_hash

:build
echo [LitUbik] Building frontend...
cd frontend
call npm run build
if errorlevel 1 goto :fail
cd ..

:migrate
if not exist frontend\dist\index.html echo [LitUbik] WARNING: no built frontend (frontend\dist) - the web UI will not load. Re-run without --no-build.
echo [LitUbik] Applying database migrations...
cd backend
.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 goto :fail
cd ..

REM -- Launch ---------------------------------------------------------------------
echo.
echo [LitUbik] Starting server on http://localhost:8000
echo [LitUbik] Teammates on your network can connect to http://%COMPUTERNAME%:8000
echo [LitUbik] (or use this machine's IP address shown by: ipconfig)
echo [LitUbik] Keep this window open. Press Ctrl+C to stop.
echo.
if "%~1"=="--no-browser" goto :serve
if "%~2"=="--no-browser" goto :serve
start "" cmd /c "timeout /t 2 >nul & start http://localhost:8000"

:serve
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
goto :eof

REM == subroutine: find a Python that is actually new enough =====================
REM `where python` is not enough: an Anaconda/Miniconda or PsychoPy install
REM earlier on PATH answers first, and building the venv on a Python that old
REM fails later and obscurely (its pip predates wheels for these packages and
REM tries to compile bcrypt from source). The `py` launcher, shipped by the
REM python.org installer, knows the real interpreters and ignores PATH order, so
REM it is asked first. Every candidate is checked for >= 3.12 before use.
:find_python
set "PY_CMD="
call :try_py "py -3"
call :try_py "py"
call :try_py "python"
exit /b 0

:try_py
if defined PY_CMD exit /b 0
%~1 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY_CMD=%~1"
exit /b 0

REM == subroutine: decide whether npm install must run ===========================
:need_install
set "NEED_INSTALL="
set "HASH_FILE=frontend\node_modules\.litubik-pkg-hash"
if not exist frontend\node_modules set "NEED_INSTALL=1" & exit /b 0
if not exist "%HASH_FILE%" set "NEED_INSTALL=1" & exit /b 0
call :hash_pkg
set /p STORED_HASH=<"%HASH_FILE%"
if /i not "%HASH_RESULT%"=="%STORED_HASH%" set "NEED_INSTALL=1"
exit /b 0

REM == subroutine: record package.json hash after a successful install ============
:save_pkg_hash
call :hash_pkg
> "frontend\node_modules\.litubik-pkg-hash" echo %HASH_RESULT%
exit /b 0

REM == subroutine: SHA256 of frontend\package.json into HASH_RESULT ===============
:hash_pkg
set "HASH_RESULT="
for /f "skip=1 delims=" %%h in ('certutil -hashfile "frontend\package.json" SHA256 2^>nul') do (
    if not defined HASH_RESULT set "HASH_RESULT=%%h"
)
set "HASH_RESULT=%HASH_RESULT: =%"
exit /b 0

REM == subroutine: download a local Node.js (no admin) ============================
:bootstrap_node
set "NODE_VER=v24.18.0"
set "NODE_URL=https://nodejs.org/dist/%NODE_VER%/node-%NODE_VER%-win-x64.zip"
set "NODE_ZIP=%TEMP%\node-%NODE_VER%-win-x64.zip"
set "NODE_TMP=%LOCALAPPDATA%\litubik\_nodetmp"
echo [LitUbik] Node.js not found - downloading a local copy (%NODE_VER%, ~35 MB, no admin needed)...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%NODE_URL%' -OutFile '%NODE_ZIP%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 exit /b 1
if exist "%NODE_TMP%" rmdir /s /q "%NODE_TMP%"
powershell -NoProfile -Command "try { Expand-Archive -Path '%NODE_ZIP%' -DestinationPath '%NODE_TMP%' -Force } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 exit /b 1
if exist "%NODE_DIR%" rmdir /s /q "%NODE_DIR%"
for /d %%d in ("%NODE_TMP%\node-*") do move "%%d" "%NODE_DIR%" >nul
rmdir /s /q "%NODE_TMP%" 2>nul
if not exist "%NODE_DIR%\npm.cmd" exit /b 1
echo [LitUbik] Node.js installed locally at %NODE_DIR%
exit /b 0

:python_fail
echo.
echo [LitUbik] Python 3.12 or newer is required, and no suitable one was found.
echo.
echo [LitUbik] What is on this machine:
py --list 2>nul
for /f "delims=" %%p in ('where python 2^>nul') do echo [LitUbik]   on PATH: %%p
echo.
echo [LitUbik] If a Python IS listed above, it is older than 3.12 - an Anaconda,
echo [LitUbik] Miniconda or bundled copy, for instance. LitUbik does not use it.
echo.
echo [LitUbik]   1. Install Python 3.12+ from https://www.python.org/downloads/
echo [LitUbik]   2. On the first installer screen, TICK "Add python.exe to PATH".
echo [LitUbik]   3. Close this window and run start.bat again.
echo.
pause
exit /b 1

:node_fail
echo.
echo [LitUbik] Node.js is needed to build the web interface, and the automatic
echo [LitUbik] download failed (no internet connection?).
echo [LitUbik]   Install Node.js LTS from https://nodejs.org/ (the green "LTS" button),
echo [LitUbik]   then run start.bat again.
echo.
pause
exit /b 1

:fail
echo.
echo [LitUbik] Something failed - see the message above.
pause
exit /b 1
