$ErrorActionPreference = 'Stop'

$repoZip = 'https://github.com/jay1125jay/flowiq-crew-operations/archive/refs/heads/main.zip'
$bootstrapUrl = 'https://raw.githubusercontent.com/jay1125jay/flowiq-crew-operations/main/btc-flow-monitor/windows/AUTO_UPDATE_AND_START.ps1'
$appRoot = Join-Path $env:LOCALAPPDATA 'BTC_FLOW_APP'
$appDir = Join-Path $appRoot 'btc-flow-monitor'
$paperDir = Join-Path $env:LOCALAPPDATA 'BTC_FLOW_PAPER'
$tempRoot = Join-Path $env:TEMP ('BTC_FLOW_UPDATE_' + [guid]::NewGuid().ToString('N'))
$zipPath = Join-Path $tempRoot 'main.zip'
$extractDir = Join-Path $tempRoot 'extract'

Write-Host '[BTC FLOW] Checking latest version...'
New-Item -ItemType Directory -Force -Path $tempRoot, $extractDir, $appRoot, $paperDir | Out-Null

try {
    # Refresh the bootstrap itself for the next launch when running from the stable bootstrap folder.
    $selfPath = $MyInvocation.MyCommand.Path
    if ($selfPath -and ($selfPath -like (Join-Path $env:LOCALAPPDATA 'BTC_FLOW_BOOTSTRAP\*'))) {
        $nextBootstrap = Join-Path $tempRoot 'AUTO_UPDATE_AND_START.ps1'
        Invoke-WebRequest -UseBasicParsing -Uri $bootstrapUrl -OutFile $nextBootstrap
        if ((Get-Item $nextBootstrap).Length -gt 100) {
            Copy-Item $nextBootstrap $selfPath -Force
        }
    }

    Invoke-WebRequest -UseBasicParsing -Uri $repoZip -OutFile $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
    $source = Join-Path $extractDir 'flowiq-crew-operations-main\btc-flow-monitor'
    if (-not (Test-Path (Join-Path $source 'pc_runtime.py'))) {
        throw 'Downloaded BTC FLOW package is invalid.'
    }

    $stage = Join-Path $appRoot 'btc-flow-monitor.new'
    $backup = Join-Path $appRoot 'btc-flow-monitor.old'
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item $source $stage -Recurse -Force

    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
    if (Test-Path $appDir) { Move-Item $appDir $backup -Force }
    Move-Item $stage $appDir -Force
    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force -ErrorAction SilentlyContinue }

    Write-Host '[PASS] BTC FLOW updated to latest main.'
    Write-Host ('[SAFE] PAPER state preserved: ' + (Join-Path $paperDir 'state'))

    $starter = Join-Path $appDir 'windows\START_BTC_FLOW.cmd'
    if (-not (Test-Path $starter)) { throw 'START_BTC_FLOW.cmd not found after update.' }
    Start-Process -FilePath $env:ComSpec -ArgumentList '/d','/c',('"' + $starter + '"') -WorkingDirectory (Split-Path $starter -Parent)
}
finally {
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
