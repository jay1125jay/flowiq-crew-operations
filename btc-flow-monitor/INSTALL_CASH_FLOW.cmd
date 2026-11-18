@echo off
setlocal
title CASH FLOW - Update
echo Updating CASH FLOW. Existing accounts and history will be preserved.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $p=Join-Path $env:TEMP 'UPDATE_CASH_FLOW_MVP.ps1'; Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/jay1125jay/flowiq-crew-operations/5703aaea3145b0a843f16acc9dbcb621d192d051/btc-flow-monitor/UPDATE_CASH_FLOW.ps1' -OutFile $p; & $p"
if errorlevel 1 (
  echo Update failed. Please send a screenshot of this window.
  pause
  exit /b 1
)
echo Update complete. The engine and dashboard will open automatically.
pause
