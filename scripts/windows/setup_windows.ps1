$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Set-Location -LiteralPath $projectRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Install Python 3.13 for Windows with the Python launcher, then reopen PowerShell."
}
foreach ($tool in @("ffmpeg", "ffprobe")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Install FFmpeg, add its bin folder to PATH, then reopen PowerShell. Missing: $tool"
    }
}
& py -3.13 -c "import sys; print(sys.version)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.13 is required for this setup script." }
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & py -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

# Kokoro-82M narration runs locally in its own Python 3.12 environment.
& py -3.12 -c "import sys; print(sys.version)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.12 is required for the local Kokoro voice environment." }
if (-not (Test-Path ".venv-kokoro\Scripts\python.exe")) {
    & py -3.12 -m venv .venv-kokoro
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Kokoro environment." }
}
$kokoro = Join-Path $projectRoot ".venv-kokoro\Scripts\python.exe"
& $kokoro -m pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw "CPU PyTorch installation failed." }
& $kokoro -m pip install -r requirements-kokoro.txt
if ($LASTEXITCODE -ne 0) { throw "Kokoro installation failed." }
& $python -m unittest discover -v
if ($LASTEXITCODE -ne 0) { throw "Regression checks failed." }
Write-Host "Setup finished. Run shorts_automation\rendering\run_preview_windows.ps1 next. No scheduled tasks or uploads were started."
