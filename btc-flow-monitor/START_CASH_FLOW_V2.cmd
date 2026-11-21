@echo off
setlocal
set "ROOT=%LOCALAPPDATA%\BTC_FLOW_V2"
if not exist "%ROOT%" mkdir "%ROOT%"
set "SCRIPT=%ROOT%\CASH_FLOW_V2_SUPERVISOR.ps1"
set "URL=https://raw.githubusercontent.com/jay1125jay/flowiq-crew-operations/feature/cash-flow-v2-release-candidate/btc-flow-monitor/CASH_FLOW_V2_SUPERVISOR.ps1"
echo CASH FLOW V2 - PAPER ONLY
echo This does not stop or overwrite V1 automatically.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile '%SCRIPT%'; if ($LASTEXITCODE -ne 0) { exit 1 }; & '%SCRIPT%'"
echo.
echo Supervisor stopped. Review the message above.
pause
endlocal
