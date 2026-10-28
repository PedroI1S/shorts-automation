# Runs one orchestrator pass: drafts/renders at most -MaxJobs queued jobs, then
# stops at human review. Never uploads. Safe to launch repeatedly: a second
# concurrent run exits immediately. NOT registered with Task Scheduler yet.
param([int]$MaxJobs = 1)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
if (-not $env:HERMES_HOME) {
    $env:HERMES_HOME = [Environment]::GetEnvironmentVariable("HERMES_HOME", "User")
}
$logDir = Join-Path $PSScriptRoot "storage\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("orchestrator_{0}.log" -f (Get-Date -Format "yyyyMMdd"))
"=== $(Get-Date -Format o) run --max-jobs $MaxJobs ===" | Add-Content -LiteralPath $log -Encoding utf8
& "$PSScriptRoot\.venv\Scripts\python.exe" orchestrator.py run --max-jobs $MaxJobs *>&1 |
    Tee-Object -FilePath $log -Append
exit $LASTEXITCODE
