# Build the Windows one-click executable (dist\LitUbik\LitUbik.exe).
# Prerequisites: backend\.venv exists (see start.bat) and frontend\dist is
# built (npm run build). Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $py)) { throw "backend\.venv missing - run start.bat once first" }
if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
    throw "frontend\dist missing - run 'npm run build' in frontend first"
}

& $py -m pip install --quiet "pyinstaller>=6.10"
Set-Location (Join-Path $root "packaging")
& $py -m PyInstaller --noconfirm --clean litubik.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $root "packaging\dist\LitUbik\LitUbik.exe"
Write-Host "`nBuilt: $exe"
Write-Host "Ship the whole 'dist\LitUbik' folder (zip it); users run LitUbik.exe."
