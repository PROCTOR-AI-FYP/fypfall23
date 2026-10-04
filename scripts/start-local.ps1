param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot 'ai-engine/.runtime/local-web'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Test-LocalEndpoint([string]$Address) {
    try {
        $reply = Invoke-WebRequest -Uri $Address -TimeoutSec 2 -UseBasicParsing
        return $reply.StatusCode -eq 200
    } catch { return $false }
}

$pidFile = Join-Path $runtimeDir 'servers.json'
$servers = if (Test-Path -LiteralPath $pidFile) {
    Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json -AsHashtable
} else { @{} }
if (-not (Test-LocalEndpoint 'http://127.0.0.1:8000/object-monitor/status')) {
    $pythonPath = Join-Path $projectRoot 'venv/Scripts/python.exe'
    $backend = Start-Process -FilePath $pythonPath -ArgumentList @('-X', 'faulthandler', '-u', '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000', '--loop', 'asyncio', '--http', 'h11') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'backend.out.log') -RedirectStandardError (Join-Path $runtimeDir 'backend.err.log') -PassThru
    $servers.backend = $backend.Id
}
if (-not (Test-LocalEndpoint 'http://127.0.0.1:5173/')) {
    $nodePath = (Get-Command node -ErrorAction Stop).Source
    $vitePath = Join-Path $projectRoot 'node_modules/vite/bin/vite.js'
    $frontend = Start-Process -FilePath $nodePath -ArgumentList @($vitePath, '--host', '127.0.0.1', '--port', '5173', '--strictPort') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.out.log') -RedirectStandardError (Join-Path $runtimeDir 'frontend.err.log') -PassThru
    $servers.frontend = $frontend.Id
}
$servers | ConvertTo-Json | Set-Content -LiteralPath $pidFile
Write-Output 'ProctorAI: http://127.0.0.1:5173/'
Write-Output "Logs: $runtimeDir"
