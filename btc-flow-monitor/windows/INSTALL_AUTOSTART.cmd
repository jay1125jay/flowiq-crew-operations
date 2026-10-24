@echo off
setlocal EnableExtensions

set "TASK_NAME=BTC FLOW PAPER Autostart"
set "STARTER=%~dp0START_BTC_FLOW.cmd"

if not exist "%STARTER%" (
  echo [FAIL] START_BTC_FLOW.cmd not found.
  echo Keep INSTALL_AUTOSTART.cmd in the btc-flow-monitor\windows folder.
  pause
  exit /b 1
)

set "BTC_FLOW_STARTER=%STARTER%"
echo Registering BTC FLOW PAPER auto-start for this Windows user...

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$taskName=$env:TASK_NAME;" ^
  "if (-not $taskName) { $taskName='BTC FLOW PAPER Autostart' };" ^
  "$starter=[IO.Path]::GetFullPath($env:BTC_FLOW_STARTER);" ^
  "$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;" ^
  "$action=New-ScheduledTaskAction -Execute $env:ComSpec -Argument ('/d /c ""{0}""' -f $starter);" ^
  "$trigger=New-ScheduledTaskTrigger -AtLogOn -User $user;" ^
  "$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew;" ^
  "$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited;" ^
  "Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'BTC FLOW PAPER ONLY - six 3M KRW 10X category engines plus separate Adaptive research runtime' -Force | Out-Null;" ^
  "$task=Get-ScheduledTask -TaskName $taskName; if (-not $task) { throw 'Task registration verification failed' };" ^
  "Write-Host ('[PASS] Registered: ' + $task.TaskName)"

if errorlevel 1 (
  echo.
  echo [FAIL] Auto-start registration failed.
  echo Try right-clicking this file and selecting Run as administrator once.
  pause
  exit /b 1
)

echo.
echo [PASS] BTC FLOW will start automatically when this Windows user logs in.
echo PAPER ONLY remains enforced by START_BTC_FLOW.cmd.
echo Existing runtime locking prevents a second PAPER writer from starting.
echo To remove auto-start, run REMOVE_AUTOSTART.cmd.
pause
exit /b 0
