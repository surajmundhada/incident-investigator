$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
$cachePath = Join-Path $projectRoot 'work\npm-cache'
if (-not (Test-Path -LiteralPath 'node_modules\vite\bin\vite.js')) {
    & npm.cmd --cache $cachePath ci
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard dependency installation failed.' }
}
Write-Output 'Dashboard: http://127.0.0.1:5173. Start the API separately on port 8001.'
& node node_modules/vite/bin/vite.js --host 127.0.0.1
if ($LASTEXITCODE -ne 0) { throw 'Dashboard server stopped with an error.' }
