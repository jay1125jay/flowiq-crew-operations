$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$startup = [Environment]::GetFolderPath('Startup')
$archive = Join-Path $env:LOCALAPPDATA 'BTC_FLOW_ORIGINAL\archived-shortcuts'
New-Item -ItemType Directory -Force -Path $archive | Out-Null
foreach ($dir in @($desktop,$startup)) {
    foreach ($name in @('BTC FLOW.lnk','BTC FLOW 1.lnk')) {
        $src = Join-Path $dir $name
        if (Test-Path -LiteralPath $src) {
            $backup = ([guid]::NewGuid().ToString('N') + '-' + $name)
            Move-Item -LiteralPath $src -Destination (Join-Path $archive $backup)
        }
    }
}
$icon = Join-Path $desktop 'BTC FLOW.url'
Set-Content -LiteralPath $icon -Encoding ascii -Value @('[InternetShortcut]', 'URL=https://jay1125jay.github.io/flowiq-crew-operations/btc-flow-monitor/dashboard.html')
$task = Get-ScheduledTask -TaskName 'BTC FLOW PAPER Autostart' -ErrorAction SilentlyContinue
if ($task) { $task | Disable-ScheduledTask | Out-Null }
Start-Process $icon
Write-Host 'PASS: original dashboard shortcut installed.'
