$ErrorActionPreference = 'Stop'

$bootstrapDir = Join-Path $env:LOCALAPPDATA 'BTC_FLOW_BOOTSTRAP'
$bootstrap = Join-Path $bootstrapDir 'AUTO_UPDATE_AND_START.ps1'
$bootstrapUrl = 'https://raw.githubusercontent.com/jay1125jay/flowiq-crew-operations/main/btc-flow-monitor/windows/AUTO_UPDATE_AND_START.ps1'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcut = Join-Path $desktop 'BTC FLOW.lnk'

New-Item -ItemType Directory -Force -Path $bootstrapDir | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri $bootstrapUrl -OutFile $bootstrap
if (-not (Test-Path $bootstrap)) { throw 'Bootstrap download failed.' }

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($shortcut)
$sc.TargetPath = 'powershell.exe'
$sc.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $bootstrap + '"'
$sc.WorkingDirectory = $bootstrapDir
$sc.Description = 'BTC FLOW PAPER ONLY - auto update then start'
$sc.IconLocation = ($env:SystemRoot + '\System32\shell32.dll,137')
$sc.Save()

Write-Host '[PASS] BTC FLOW auto-update installed.'
Write-Host ('[PASS] Desktop shortcut: ' + $shortcut)
Write-Host '[NEXT] Double-click BTC FLOW. It will update first, then start.'
