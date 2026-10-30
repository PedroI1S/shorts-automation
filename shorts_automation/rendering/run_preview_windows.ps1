$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run scripts\windows\setup_windows.ps1 first." }
& $python -m shorts_automation.rendering.speech_preview --audio-metadata storage/audio/fish_093cbb6143f5270b.json --output-name windows_caption_test.mp4
if ($LASTEXITCODE -ne 0) { throw "The preview failed. Copy the error text for troubleshooting." }
Write-Host "Preview: $projectRoot\storage\output\windows_caption_test.mp4"
