# Runs one orchestrator pass: drafts/renders at most -MaxJobs queued jobs, then
# stops at human review. Never uploads. Safe to launch repeatedly: a second
# concurrent run exits immediately. Manual helper; the installed task uses run_production_windows.ps1.
param([int]$MaxJobs = 1)
$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = "1"
if (-not $env:HERMES_HOME) {
    $env:HERMES_HOME = [Environment]::GetEnvironmentVariable("HERMES_HOME", "User")
}
$logDir = Join-Path $projectRoot "storage\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("orchestrator_{0}.log" -f (Get-Date -Format "yyyyMMdd"))
"=== $(Get-Date -Format o) run --max-jobs $MaxJobs ===" | Add-Content -LiteralPath $log -Encoding utf8
& "$projectRoot\.venv\Scripts\python.exe" -m shorts_automation.automation.orchestrator run --max-jobs $MaxJobs *>&1 |
    Tee-Object -FilePath $log -Append
exit $LASTEXITCODE
