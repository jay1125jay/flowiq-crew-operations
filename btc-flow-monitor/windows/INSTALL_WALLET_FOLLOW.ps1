param([switch]$Run)
$ErrorActionPreference='Stop'
$dir=Join-Path $env:LOCALAPPDATA 'BTC_FLOW_WALLET_FOLLOW'
New-Item -ItemType Directory -Force $dir | Out-Null
$launcher=Join-Path $dir 'INSTALL_WALLET_FOLLOW.ps1'
$python=Join-Path $dir 'venv\Scripts\python.exe'
$script=Join-Path $dir 'pc_wallet_follow.py'
if (!$Run) {
    Get-Command git -ErrorAction Stop | Out-Null
    Copy-Item $PSCommandPath $launcher -Force
    & py -3.12 -m venv (Join-Path $dir 'venv')
    if ($LASTEXITCODE) { throw 'Python 3.12 required' }
    & $python -m pip install websockets==15.0.1
    if ($LASTEXITCODE) { throw 'Dependency install failed' }
    Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/jay1125jay/flowiq-crew-operations/main/btc-flow-monitor/pc_wallet_follow.py' -OutFile $script
    $shell=New-Object -ComObject WScript.Shell
    $link=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'BTC FLOW wallet observer.lnk'))
    $link.TargetPath=(Get-Command powershell.exe).Source
    $link.Arguments='-NoProfile -ExecutionPolicy Bypass -File "'+$launcher+'" -Run'
    $link.WindowStyle=7
    $link.Save()
}
$mutex=New-Object System.Threading.Mutex($false,'Local\BTCFlowOriginalWalletWriter')
try {
    try {$owner=$mutex.WaitOne(0)} catch [System.Threading.AbandonedMutexException] {$owner=$true}
    if (!$owner) {return}
    while ($true) {
        & $python $script
        Write-Host 'PC observer stopped; retry in 60 seconds.'
        Start-Sleep -Seconds 60
    }
} finally {if ($owner){$mutex.ReleaseMutex()};$mutex.Dispose()}
