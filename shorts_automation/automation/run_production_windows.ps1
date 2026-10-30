param([switch]$Watch)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
if (-not $env:HERMES_HOME) {
    $env:HERMES_HOME = [Environment]::GetEnvironmentVariable('HERMES_HOME', 'User')
}
$logDir = Join-Path $projectRoot 'storage\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$watchLock = $null
if ($Watch) {
    try {
        $watchLock = [System.IO.File]::Open((Join-Path $projectRoot 'storage\production_watch.lock'),
            [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    } catch { exit 0 }
}
try {
    do {
        $log = Join-Path $logDir ('production_{0}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
        "=== $(Get-Date -Format o) production pass ===" | Add-Content -LiteralPath $log -Encoding utf8
        $ErrorActionPreference = 'Continue'
        & "$projectRoot\.venv\Scripts\python.exe" -m shorts_automation.automation.production run *>&1 |
            ForEach-Object {
                $line = $_.ToString()
                $line | Add-Content -LiteralPath $log -Encoding utf8
                Write-Output $line
            }
        $passExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        "Exit: $passExit" | Add-Content -LiteralPath $log -Encoding utf8
        if (-not $Watch) { exit $passExit }
        Start-Sleep -Seconds 1800
    } while ($Watch)
} finally {
    if ($watchLock) { $watchLock.Dispose() }
}
