param([switch]$Install, [switch]$Background)
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'BTC_FLOW_ORIGINAL'
$launcher = Join-Path $root 'ORIGINAL_PC.ps1'
$repo = 'jay1125jay/flowiq-crew-operations'
New-Item -ItemType Directory -Force -Path $root | Out-Null
if ($Install) {
    Copy-Item -LiteralPath $PSCommandPath -Destination $launcher -Force
    $icon = Join-Path $root 'cash-flow.ico'
    [IO.File]::WriteAllBytes($icon, [Convert]::FromBase64String('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'))
    $shell = New-Object -ComObject WScript.Shell
    foreach ($folder in @('Desktop','Startup')) {
        $folderPath = [Environment]::GetFolderPath($folder)
        $displayName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('7LqQ7ImsIO2UjOuhnOyasA=='))
        $shortcut = $shell.CreateShortcut((Join-Path $folderPath ($displayName + '.lnk')))
        $shortcut.TargetPath = (Get-Command powershell.exe).Source
        $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '"'
        if ($folder -eq 'Startup') { $shortcut.Arguments += ' -Background' }
        $shortcut.WorkingDirectory = $root
        $shortcut.WindowStyle = 7
        $shortcut.IconLocation = $icon + ',0'
        $shortcut.Save()
        $oldLink = Join-Path $folderPath 'BTC FLOW 1.lnk'
        if (Test-Path -LiteralPath $oldLink) {
            if ($shell.CreateShortcut($oldLink).Arguments -like ('*' + $launcher + '*')) {
                Remove-Item -LiteralPath $oldLink
            }
        }
    }
}
$mutex = New-Object System.Threading.Mutex($false,'Local\BTCFlowOriginalDashboard')
try {
    try { $owner = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owner = $true }
    if (-not $owner) {
        if (-not $Background) { Start-Process 'http://127.0.0.1:8081/' }
        return
    }
    $installed = Join-Path $root 'current.txt'
    $active = if (Test-Path $installed) { (Get-Content $installed -Raw).Trim() }
    $work = Join-Path $root ([guid]::NewGuid().ToString('N'))
    try {
        $rev = (Invoke-RestMethod "https://api.github.com/repos/$repo/commits/main" -TimeoutSec 20).sha
        if ($rev -notmatch '^[a-f0-9]{40}$') { throw 'Invalid revision' }
        $release = Join-Path $root $rev
        if (-not (Test-Path $release)) {
            New-Item -ItemType Directory -Path $work | Out-Null
            $archive = Join-Path $work 'repo.zip'
            Invoke-WebRequest -UseBasicParsing "https://github.com/$repo/archive/$rev.zip" -OutFile $archive -TimeoutSec 180
            Expand-Archive $archive (Join-Path $work 'src')
            $app = Join-Path $work "src\flowiq-crew-operations-$rev\btc-flow-monitor"
            foreach ($file in @('original_pc_runtime.py','trader-discovery\category-paper.json','windows\ORIGINAL_PC.ps1')) {
                if (-not (Test-Path (Join-Path $app $file))) { throw "Missing $file" }
            }
            Move-Item -LiteralPath $app -Destination $release
        }
        $next = "$installed.new"
        Set-Content -LiteralPath $next -Value $rev -Encoding ascii
        if (Test-Path $installed) { [IO.File]::Replace($next,$installed,$null) } else { Move-Item $next $installed }
        $previous = $active
        $active = $rev
        if ($previous -and $previous -ne $rev -and $previous -match '^[a-f0-9]{40}$') {
            Remove-Item (Join-Path $root $previous) -Recurse -Force -ErrorAction SilentlyContinue
        }
    } catch {
        if (-not $active) { throw }
        Write-Warning "Update unavailable. Using installed release. $_"
    } finally {
        if (Test-Path $work) { Remove-Item $work -Recurse -Force }
    }
    $app = Join-Path $root $active
    $python = Join-Path $root 'venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        & py -3.12 -m venv (Join-Path $root 'venv')
        if ($LASTEXITCODE) { throw 'Python 3.12 setup failed' }
    }
    & $python -m pip install --disable-pip-version-check -r (Join-Path $app 'realtime\requirements.txt')
    if ($LASTEXITCODE) { throw 'Dependency setup failed' }
    $env:PAPER_ONLY='true'
    $env:REAL_TRADING='false'
    $env:PYTHONUTF8='1'
    $state = Join-Path $root 'original-dashboard-state'
    $options = @('--state-dir',$state,'--port','8081','--share-phone')
    if (-not $Background) { $options += '--open-browser' }
    & $python (Join-Path $app 'original_pc_runtime.py') @options
    if ($LASTEXITCODE) { throw 'Original dashboard engine stopped with an error' }
} catch {
    $_ | Out-String | Set-Content (Join-Path $root 'last-error.txt')
    throw
} finally {
    if ($owner) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
