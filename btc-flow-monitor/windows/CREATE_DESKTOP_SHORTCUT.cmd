@echo off
setlocal EnableExtensions

set "STARTER=%~dp0START_BTC_FLOW.cmd"
if not exist "%STARTER%" (
  echo [FAIL] START_BTC_FLOW.cmd not found.
  echo Keep this file in btc-flow-monitor\windows.
  pause
  exit /b 1
)

set "BTC_FLOW_STARTER=%STARTER%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$desktop=[Environment]::GetFolderPath('Desktop');" ^
  "$shortcut=Join-Path $desktop 'BTC FLOW.lnk';" ^
  "$ws=New-Object -ComObject WScript.Shell;" ^
  "$sc=$ws.CreateShortcut($shortcut);" ^
  "$sc.TargetPath=$env:ComSpec;" ^
  "$sc.Arguments=('/d /c ""{0}""' -f [IO.Path]::GetFullPath($env:BTC_FLOW_STARTER));" ^
  "$sc.WorkingDirectory=Split-Path -Parent ([IO.Path]::GetFullPath($env:BTC_FLOW_STARTER));" ^
  "$sc.Description='BTC FLOW PAPER ONLY';" ^
  "$sc.IconLocation=($env:SystemRoot + '\System32\shell32.dll,137');" ^
  "$sc.Save();" ^
  "if (-not (Test-Path $shortcut)) { throw 'Shortcut creation failed' };" ^
  "Write-Host ('[PASS] Created desktop shortcut: ' + $shortcut)"

if errorlevel 1 (
  echo.
  echo [FAIL] Desktop shortcut creation failed.
  pause
  exit /b 1
)

echo.
echo [PASS] Desktop icon created: BTC FLOW
echo Double-click BTC FLOW on the desktop to start the PAPER runtime.
pause
exit /b 0
