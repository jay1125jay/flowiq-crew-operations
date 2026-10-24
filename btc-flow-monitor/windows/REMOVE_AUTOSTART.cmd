@echo off
setlocal EnableExtensions
set "TASK_NAME=BTC FLOW PAPER Autostart"

echo Removing BTC FLOW PAPER auto-start for this Windows user...

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$taskName=$env:TASK_NAME;" ^
  "if (-not $taskName) { $taskName='BTC FLOW PAPER Autostart' };" ^
  "$task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue;" ^
  "if ($task) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false; Write-Host ('[PASS] Removed: ' + $taskName) } else { Write-Host ('[PASS] Already absent: ' + $taskName) }"

if errorlevel 1 (
  echo.
  echo [FAIL] Auto-start removal failed.
  echo Try right-clicking this file and selecting Run as administrator once.
  pause
  exit /b 1
)

echo.
echo Saved PAPER account state was not deleted.
echo You can still start BTC FLOW manually with START_BTC_FLOW.cmd.
pause
exit /b 0
