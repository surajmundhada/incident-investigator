param([switch]$LiveDemo, [switch]$Knowledge, [switch]$Agent, [switch]$Cache, [switch]$Artifacts)
$ErrorActionPreference = 'Stop'
if ($Cache -and -not $Knowledge) { throw '-Cache requires -Knowledge.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.env')) {
    throw 'Create the local .env using .env.example before starting Compose.'
}
$dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($dockerCommand) {
    $dockerPath = $dockerCommand.Source
} else {
    $dockerCandidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    )
    $dockerPath = $dockerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $dockerPath) {
    throw 'Docker CLI was not found. Install Docker Desktop and start its Linux engine.'
}
# Docker also launches its credential helper by name; make sibling tools visible
# to this launcher process without modifying the user's persistent system PATH.
$env:PATH = (Split-Path -Parent $dockerPath) + [IO.Path]::PathSeparator + $env:PATH
$composeArguments = @('compose', '-f', 'compose.yaml')
if ($LiveDemo) { $composeArguments += @('-f', 'compose.demo.yaml') }
if ($Knowledge) { $composeArguments += @('-f', 'compose.knowledge.yaml') }
if ($Agent) { $composeArguments += @('-f', 'compose.agent.yaml') }
if ($Cache) { $composeArguments += @('-f', 'compose.cache.yaml') }
if ($Artifacts) { $composeArguments += @('-f', 'compose.artifacts.yaml') }
if (-not $LiveDemo) { $composeArguments += @('--profile', 'fixture') }
& $dockerPath @composeArguments up --build -d --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose did not start successfully.' }
& $dockerPath compose ps
Write-Output 'Default PostgreSQL-backed API: http://127.0.0.1:8001/docs (API_PORT in .env can override it).'
if ($LiveDemo) {
    Write-Output 'Live demo: http://127.0.0.1:8002/docs; operator controls: http://127.0.0.1:8003/docs'
}
if ($Knowledge) { Write-Output 'Versioned hybrid knowledge search enabled: POST /api/knowledge/search' }
if ($Agent) { Write-Output 'Agent runtime installed; hosted calls require explicit AGENT_MODE and provider configuration.' }
if ($Cache) { Write-Output 'Optional Redis embedding/retrieval caching enabled; PostgreSQL remains authoritative.' }
if ($Artifacts) { Write-Output 'Local durable artifact archive and upload reconciliation enabled; no AWS connection.' }
