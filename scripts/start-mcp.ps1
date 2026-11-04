param([string]$ApiBaseUrl = 'http://127.0.0.1:8001')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create the project .venv and install the optional MCP requirements first.' }
$env:PYTHONPATH = Join-Path $projectRoot 'backend'
$env:MCP_API_BASE_URL = $ApiBaseUrl
# stdout belongs exclusively to the MCP wire. Do not print setup messages here.
& $pythonPath -u -m investigator.mcp_server
exit $LASTEXITCODE
