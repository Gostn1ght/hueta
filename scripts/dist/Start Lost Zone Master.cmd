@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist "UPDATING.lock" (echo Lost Zone update is in progress. & pause & exit /b 1)
if not exist "dedicated\LostZoneMaster.exe" (echo Missing dedicated\LostZoneMaster.exe. Extract the complete server package. & pause & exit /b 1)
if not exist "dedicated\sqlite3.dll" (echo Missing dedicated\sqlite3.dll. Extract the complete server package. & pause & exit /b 1)
set "LZ_MASTER_ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath (Join-Path $env:LZ_MASTER_ROOT dedicated) -File | Unblock-File -ErrorAction Stop"
if errorlevel 1 (echo Cannot unblock downloaded runtime files. & pause & exit /b 1)
start "" "dedicated\LostZoneMaster.exe"
exit /b 0
