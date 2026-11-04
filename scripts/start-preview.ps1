$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = Join-Path $projectRoot 'backend'
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -m investigator.preview
