@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto missing
py -3.12 -c "import sys; assert sys.version_info[:2] == (3,12)" >nul 2>nul
if errorlevel 1 goto missing
set "BTC_HOME=%LOCALAPPDATA%\BTC_FLOW_PAPER"
if not exist "%BTC_HOME%" mkdir "%BTC_HOME%"
if not exist "%BTC_HOME%\venv\Scripts\python.exe" (
  echo Creating BTC FLOW Python environment...
  py -3.12 -m venv "%BTC_HOME%\venv"
  if errorlevel 1 goto failed
)
"%BTC_HOME%\venv\Scripts\python.exe" -c "import websockets; assert websockets.__version__ == '15.0.1'" >nul 2>nul
if errorlevel 1 (
  echo Installing public market data client...
  "%BTC_HOME%\venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0..\realtime\requirements.txt"
  if errorlevel 1 goto failed
)
set "PAPER_ONLY=true"
set "REAL_TRADING=false"
set "PYTHONUTF8=1"
echo Keep this window open. Press Ctrl+C to stop safely.
"%BTC_HOME%\venv\Scripts\python.exe" "%~dp0..\realtime_runtime.py" --state-dir "%BTC_HOME%\state" --host 127.0.0.1 --port 8080 --open-browser
if errorlevel 1 goto failed
pause
exit /b 0
:missing
echo Python 3.12 with the Python Launcher is required.
echo Install it from https://www.python.org/downloads/windows/
echo Then double-click START_BTC_FLOW.cmd again.
pause
exit /b 1
:failed
echo BTC FLOW stopped with an error. Saved PAPER state has not been deleted.
echo If already running, use the existing window: http://127.0.0.1:8080/
pause
exit /b 1
