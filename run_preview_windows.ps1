$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run setup_windows.ps1 first." }
& $python speech_preview.py --audio-metadata storage/audio/fish_093cbb6143f5270b.json --output-name windows_caption_test.mp4
if ($LASTEXITCODE -ne 0) { throw "The preview failed. Copy the error text for troubleshooting." }
Write-Host "Preview: $PSScriptRoot\storage\output\windows_caption_test.mp4"
