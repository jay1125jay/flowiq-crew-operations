$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'BTC_FLOW_WALLET_FOLLOW'
$python = Join-Path $root 'venv\Scripts\python.exe'
$engine = Join-Path $root 'pc_wallet_follow.py'
$oldLauncher = Join-Path $root 'INSTALL_WALLET_FOLLOW.ps1'
$launcher = Join-Path $root 'START_CASH_FLOW.ps1'
if (!(Test-Path $python) -or !(Test-Path $engine)) {
    throw 'Existing CASH FLOW installation not found. Nothing was changed.'
}
$download = Join-Path $root 'pc_wallet_follow.download.py'
$url = 'https://raw.githubusercontent.com/jay1125jay/flowiq-crew-operations/main/btc-flow-monitor/pc_wallet_follow.py'
Invoke-WebRequest -UseBasicParsing $url -OutFile $download
& $python -m py_compile $download
if ($LASTEXITCODE -ne 0) { throw 'Downloaded engine failed validation.' }
& $python -c 'from websockets.asyncio.client import connect'
if ($LASTEXITCODE -ne 0) { throw 'WebSocket dependency is missing.' }

& $python -m pip install qrcode==8.2
if ($LASTEXITCODE -ne 0) { throw 'QR dependency installation failed. Existing engine unchanged.' }

# Download and validate first; keep the existing database and account files.
$backup = "$engine.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
Copy-Item -LiteralPath $engine -Destination $backup
Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.Name -match '^powershell\.exe$' -and
    ($_.CommandLine -like "*$oldLauncher*" -or $_.CommandLine -like "*$launcher*")
} | ForEach-Object { & taskkill.exe /PID $_.ProcessId /T /F }
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -like "*$engine*"
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Move-Item -LiteralPath $download -Destination $engine -Force

@'
$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'CASH FLOW - PAPER Engine'
$root = $PSScriptRoot
$log = Join-Path $root 'engine-console.log'
$mutex = New-Object System.Threading.Mutex($false, 'Local\BTCFlowOriginalWalletWriter')
$owner = $false
try {
    try { $owner = $mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $owner = $true }
    if (!$owner) {
        Write-Host 'Engine is already running. Showing its log; no second engine started.'
        if (Test-Path $log) { Get-Content -LiteralPath $log -Tail 40 -Wait }
        else { Read-Host 'Log not available yet. Press Enter to close' }
        return
    }
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 10MB) {
        Move-Item $log "$log.previous" -Force
    }
    Start-Transcript -Path $log -Append
    try {
        while ($true) {
            Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ENGINE START - PAPER ONLY"
            & (Join-Path $root 'venv\Scripts\python.exe') -u (Join-Path $root 'pc_wallet_follow.py')
            Write-Host "Engine exited: $LASTEXITCODE. Retry in 30 seconds."
            Start-Sleep -Seconds 30
        }
    } finally { Stop-Transcript }
} finally {
    if ($owner) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
'@ | Set-Content -LiteralPath $launcher -Encoding UTF8

$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$targets = @()
Get-ChildItem -LiteralPath $desktop -Filter '*.lnk' | ForEach-Object {
    $s = $ws.CreateShortcut($_.FullName)
    if ($s.Arguments -like "*$oldLauncher*" -or $s.Arguments -like "*$launcher*") {
        $targets += $_.FullName
    }
}
if (!$targets.Count) { $targets += Join-Path $desktop 'CASH FLOW Engine.lnk' }
$targets += Join-Path ([Environment]::GetFolderPath('Startup')) 'BTC FLOW wallet observer.lnk'
foreach ($path in $targets) {
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $s.Arguments = '-NoProfile -NoExit -ExecutionPolicy Bypass -File "' + $launcher + '"'
    $s.WorkingDirectory = $root
    $s.WindowStyle = 1
    $s.Save()
}
Start-Process powershell.exe -ArgumentList ('-NoProfile -NoExit -ExecutionPolicy Bypass -File "' + $launcher + '"')
Write-Host 'UPDATED: Engine and shortcuts. Existing PAPER history and pending database preserved.'
Write-Host "Backup: $backup"
