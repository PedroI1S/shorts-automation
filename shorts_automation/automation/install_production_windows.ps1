# Installs a per-user task. If Windows denies Task Scheduler registration, use
# the same hidden Startup-folder approach as Hermes. No admin/password required.
param([switch]$Start)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$runner = Join-Path $PSScriptRoot 'run_production_windows.ps1'
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.venv\Scripts\python.exe'))) {
    throw 'Run scripts\windows\setup_windows.ps1 before installing production.'
}
$taskName = 'ShortsAutomationProduction'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $runner
$deploymentDir = Join-Path $projectRoot 'deployment'
New-Item -ItemType Directory -Path $deploymentDir -Force | Out-Null
$startupPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'ShortsAutomationProduction.vbs'
try {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
    $periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 30)
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
    $task = New-ScheduledTask -Action $action -Trigger @($periodic, $logon) -Principal $principal -Settings $settings
    $task | Export-ScheduledTask | Set-Content -LiteralPath (Join-Path $deploymentDir 'production-task.xml') -Encoding utf8
    Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
    # Only remove this installer's exact fallback after a successful task registration.
    if (Test-Path -LiteralPath $startupPath) { Remove-Item -LiteralPath $startupPath }
    if ($Start) { Start-ScheduledTask -TaskName $taskName }
    $mode = 'task_scheduler'
    Write-Host "Installed $taskName (current user, every 30 minutes and at logon)."
} catch {
    if ($_.Exception -isnot [Microsoft.Management.Infrastructure.CimException] -and
        $_.Exception.Message -notmatch 'denied|0x80070005') { throw }
    $watchArguments = 'powershell.exe ' + $arguments + ' -Watch'
    $escaped = $watchArguments.Replace('"', '""')
    $vbs = "Set shell = CreateObject(""WScript.Shell"")`r`nshell.Run ""$escaped"", 0, False`r`n"
    [System.IO.File]::WriteAllText($startupPath, $vbs, [System.Text.Encoding]::Unicode)
    if ($Start) { Start-Process -FilePath 'wscript.exe' -ArgumentList ('"{0}"' -f $startupPath) -WindowStyle Hidden }
    $mode = 'startup_watchdog'
    Write-Host 'Task Scheduler access denied; installed hidden per-user Startup watchdog (every 30 minutes).'
}
@{mode=$mode; installed_at=(Get-Date -Format o); root=$projectRoot; task=$taskName; startup=$startupPath} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $deploymentDir 'production-install.json') -Encoding utf8
