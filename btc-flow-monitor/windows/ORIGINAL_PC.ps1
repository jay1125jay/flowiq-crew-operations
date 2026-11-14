param([switch]$Install, [switch]$Background)
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'BTC_FLOW_ORIGINAL'
$launcher = Join-Path $root 'ORIGINAL_PC.ps1'
$repo = 'jay1125jay/flowiq-crew-operations'
New-Item -ItemType Directory -Force -Path $root | Out-Null
if ($Install) {
    Copy-Item -LiteralPath $PSCommandPath -Destination $launcher -Force
    $shell = New-Object -ComObject WScript.Shell
    foreach ($folder in @('Desktop','Startup')) {
        $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath($folder)) 'BTC FLOW 1.lnk'))
        $shortcut.TargetPath = (Get-Command powershell.exe).Source
        $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '"'
        if ($folder -eq 'Startup') { $shortcut.Arguments += ' -Background' }
        $shortcut.WorkingDirectory = $root
        $shortcut.WindowStyle = 7
        $shortcut.Save()
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
