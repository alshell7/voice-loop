$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDirectory '.venv/Scripts/pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install the package first. See README.md.'
}
Start-Process -FilePath $pythonPath -ArgumentList '-m', 'voiceloop' -WorkingDirectory $projectDirectory -WindowStyle Hidden
