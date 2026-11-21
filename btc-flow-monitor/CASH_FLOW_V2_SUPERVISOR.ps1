param()
$ErrorActionPreference = 'Stop'
$RepoUrl = 'https://github.com/jay1125jay/flowiq-crew-operations.git'
$Branch = 'feature/cash-flow-v2-release-candidate'
$Root = Join-Path $env:LOCALAPPDATA 'BTC_FLOW_V2'
$RepoDir = Join-Path $Root 'repo'
$EngineDir = Join-Path $RepoDir 'btc-flow-monitor'
$Venv = Join-Path $Root 'venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$StopFile = Join-Path $EngineDir 'STOP_CASH_FLOW_V2'
$BackupRoot = Join-Path $Root 'backups'
$script:EngineProcess = $null
$script:OutLog = $null
$script:ErrLog = $null

function Invoke-Git {
    param([string]$Directory, [string[]]$Arguments)
    & git -C $Directory @Arguments
    if ($LASTEXITCODE -ne 0) { throw "git failed: $($Arguments -join ' ')" }
}

function Test-LegacyEngine {
    $found = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'pc_wallet_follow\.py' -and $_.CommandLine -notmatch 'pc_wallet_follow_v2\.py') -or
        ($_.Name -match '^powershell\.exe$' -and $_.CommandLine -match 'START_CASH_FLOW\.ps1|INSTALL_WALLET_FOLLOW\.ps1')
    }
    return @($found).Count -gt 0
}

function Install-Environment {
    if (!(Test-Path $Python)) {
        New-Item -ItemType Directory -Force -Path $Root | Out-Null
        & py -3 -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3 venv creation failed.' }
    }
    & $Python -m pip install --disable-pip-version-check 'websockets==15.0.1' 'qrcode==8.2'
    if ($LASTEXITCODE -ne 0) { throw 'V2 Python dependencies could not be installed.' }
    & $Python -c 'from websockets.asyncio.client import connect; import qrcode'
    if ($LASTEXITCODE -ne 0) { throw 'V2 dependency verification failed.' }
}

function Start-Engine {
    if (Test-Path $StopFile) { Remove-Item -LiteralPath $StopFile -Force }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $script:OutLog = Join-Path $Root "engine-$stamp.out.log"
    $script:ErrLog = Join-Path $Root "engine-$stamp.err.log"
    $script:EngineProcess = Start-Process -FilePath $Python -ArgumentList @('-u', (Join-Path $EngineDir 'pc_wallet_follow_v2.py')) -WorkingDirectory $EngineDir -PassThru -NoNewWindow -RedirectStandardOutput $script:OutLog -RedirectStandardError $script:ErrLog
    Write-Host "V2 engine process started: PID $($script:EngineProcess.Id)"
}

function Stop-Engine {
    if (!$script:EngineProcess) { return }
    $process = Get-Process -Id $script:EngineProcess.Id -ErrorAction SilentlyContinue
    if (!$process) { $script:EngineProcess = $null; return }
    New-Item -ItemType File -Force -Path $StopFile | Out-Null
    Write-Host 'Waiting for V2 graceful shutdown...'
    Wait-Process -Id $script:EngineProcess.Id -Timeout 300 -ErrorAction Stop
    $script:EngineProcess = $null
    if (Test-Path $StopFile) { Remove-Item -LiteralPath $StopFile -Force }
}

function Wait-EngineHealth {
    param([int]$TimeoutSeconds = 300)
    $until = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $until) {
        if (!$script:EngineProcess -or $script:EngineProcess.HasExited) {
            if (Test-Path $script:ErrLog) { Get-Content $script:ErrLog -Tail 40 | Write-Host }
            return $false
        }
        if ((Test-Path $script:OutLog) -and (Select-String -Path $script:OutLog -Pattern 'V2_WS_CONNECTED' -Quiet)) {
            $ledgerPath = Join-Path (Join-Path $EngineDir 'trader-discovery') 'wallet-paper-v2.json'
            if (Test-Path $ledgerPath) {
                try {
                    $ledger = Get-Content -LiteralPath $ledgerPath -Raw | ConvertFrom-Json
                    if ($ledger.paper_only -eq $true -and $ledger.real_trading_enabled -eq $false -and
                        [int]$ledger.observed_count -gt 0 -and @($ledger.wallets.PSObject.Properties).Count -eq 5) {
                        return $true
                    }
                } catch {}
            }
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Invoke-TestSuite {
    param([string]$Directory)
    $work = Join-Path $Directory 'btc-flow-monitor'
    $files = @('cash_flow_v2_core.py', 'wallet_paper_v2.py', 'pc_wallet_follow_v2.py', 'wallet_phone_v2.py', 'test_cash_flow_v2_core.py', 'test_wallet_paper_v2.py', 'test_wallet_phone_v2.py')
    Push-Location $work
    try {
        & $Python -m py_compile $files
        if ($LASTEXITCODE -ne 0) { return $false }
        & $Python -m unittest -v test_cash_flow_v2_core.py test_wallet_paper_v2.py test_wallet_phone_v2.py
        return ($LASTEXITCODE -eq 0)
    } finally { Pop-Location }
}

function Test-PowerShellSyntax {
    param([string]$FilePath)
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($FilePath, [ref]$tokens, [ref]$errors) | Out-Null
    return ($errors.Count -eq 0)
}

function Backup-V2Data {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $folder = Join-Path $BackupRoot $stamp
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $script:BackupLedgerExisted = Test-Path (Join-Path $EngineDir 'trader-discovery\wallet-paper-v2.json')
    $script:BackupDbExisted = Test-Path (Join-Path $EngineDir 'pending-paper-v2.sqlite3')
    if ($script:BackupLedgerExisted) { Copy-Item (Join-Path $EngineDir 'trader-discovery\wallet-paper-v2.json') $folder }
    if ($script:BackupDbExisted) { Copy-Item (Join-Path $EngineDir 'pending-paper-v2.sqlite3') $folder }
    return $folder
}

function Restore-V2Data {
    param([string]$Folder)
    $ledger = Join-Path $EngineDir 'trader-discovery\wallet-paper-v2.json'
    $db = Join-Path $EngineDir 'pending-paper-v2.sqlite3'
    if ($script:BackupLedgerExisted) { Copy-Item (Join-Path $Folder 'wallet-paper-v2.json') $ledger -Force }
    elseif (Test-Path $ledger) { Remove-Item $ledger -Force }
    if ($script:BackupDbExisted) { Copy-Item (Join-Path $Folder 'pending-paper-v2.sqlite3') $db -Force }
    elseif (Test-Path $db) { Remove-Item $db -Force }
}

if (Test-LegacyEngine) {
    throw 'V1 CASH FLOW is still running. Close its engine window with Ctrl+C first. V2 will not force-kill V1 or run both engines together.'
}
if (!(Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git for Windows is required.' }
New-Item -ItemType Directory -Force -Path $Root | Out-Null
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

if (!(Test-Path (Join-Path $RepoDir '.git'))) {
    & git clone --depth 1 --filter=blob:none --sparse --branch $Branch $RepoUrl $RepoDir
    if ($LASTEXITCODE -ne 0) { throw 'V2 repository download failed.' }
    Invoke-Git $RepoDir @('sparse-checkout', 'set', 'btc-flow-monitor')
} else {
    Invoke-Git $RepoDir @('fetch', '--depth=1', 'origin', $Branch)
    Invoke-Git $RepoDir @('checkout', $Branch)
    Invoke-Git $RepoDir @('reset', '--hard', "origin/$Branch")
}
Install-Environment
if (!(Invoke-TestSuite $RepoDir)) { throw 'V2 pre-start tests failed. Existing data and V1 are untouched.' }

$localSha = (& git -C $RepoDir rev-parse HEAD).Trim()
Start-Engine
if (!(Wait-EngineHealth 300)) {
    Stop-Engine
    throw 'V2 startup health check failed. No V1 files were changed.'
}
Write-Host 'V2 is healthy. Automatic code update checks are active. Keep this supervisor window open.'

try {
    while ($true) {
        Start-Sleep -Seconds 60
        Invoke-Git $RepoDir @('fetch', '--depth=1', 'origin', $Branch)
        $remoteSha = (& git -C $RepoDir rev-parse "origin/$Branch").Trim()
        $localSha = (& git -C $RepoDir rev-parse HEAD).Trim()
        if ($remoteSha -eq $localSha) { continue }

        $testDir = Join-Path $Root ("test-" + $remoteSha.Substring(0, 8))
        if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
        Invoke-Git $RepoDir @('worktree', 'add', '--detach', $testDir, "origin/$Branch")
        Invoke-Git $testDir @('sparse-checkout', 'set', 'btc-flow-monitor')
        $testsPassed = $false
        try {
            $testsPassed = Invoke-TestSuite $testDir
            $candidateSupervisor = Join-Path (Join-Path $testDir 'btc-flow-monitor') 'CASH_FLOW_V2_SUPERVISOR.ps1'
            if ($testsPassed -and (Test-Path $candidateSupervisor)) {
                $testsPassed = Test-PowerShellSyntax $candidateSupervisor
            }
        } finally { Invoke-Git $RepoDir @('worktree', 'remove', '--force', $testDir) }
        if (!$testsPassed) {
            Write-Host 'UPDATE REJECTED: V2 tests failed. Current engine remains running.'
            continue
        }

        $oldSha = $localSha
        $backup = Backup-V2Data
        Stop-Engine
        try {
            Invoke-Git $RepoDir @('reset', '--hard', $remoteSha)
            Start-Engine
            if (!(Wait-EngineHealth 300)) { throw 'New version health check failed.' }
            $localSha = $remoteSha
            Write-Host "AUTO UPDATE PASS: $localSha"
        } catch {
            Write-Host "AUTO UPDATE ROLLBACK: $($_.Exception.Message)"
            Stop-Engine
            Invoke-Git $RepoDir @('reset', '--hard', $oldSha)
            Restore-V2Data $backup
            Start-Engine
            if (!(Wait-EngineHealth 300)) { throw 'Rollback engine failed its health check.' }
            $localSha = $oldSha
        }
    }
} finally {
    Stop-Engine
}
